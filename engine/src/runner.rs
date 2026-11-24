use std::collections::{HashSet, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use sha2::{Digest, Sha256};

pub fn run_file(file_path: &str, program_args: &[String], raw_errors: bool) -> i32 {
    let source_path = Path::new(file_path);
    if !source_path.exists() {
        eprintln!("Error: file not found: {}", file_path);
        return 1;
    }

    let base_dir = dirs::home_dir().unwrap().join(".hlowld");
    let toolchains_dir = base_dir.join("toolchains");
    let cache_dir = base_dir.join("cache");

    if let Err(error) = fs::create_dir_all(&cache_dir) {
        eprintln!("Error: failed to create cache directory: {}", error);
        return 1;
    }

    let extension = source_path
        .extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.to_lowercase())
        .unwrap_or_default();

    match extension.as_str() {
        "ts" | "js" => run_bun(file_path, program_args, &toolchains_dir),
        "c" | "cpp" => run_zig(
            file_path,
            program_args,
            &toolchains_dir,
            &cache_dir,
            &extension,
            raw_errors,
        ),
        "rs" => run_rust(
            file_path,
            program_args,
            &toolchains_dir,
            &cache_dir,
            raw_errors,
        ),
        _ => {
            eprintln!("Unsupported extension. Supported: .c, .cpp, .rs, .ts, .js");
            1
        }
    }
}

fn clean_path(path: &Path) -> PathBuf {
    #[cfg(windows)]
    {
        let path_string = path.to_string_lossy();
        if let Some(rest) = path_string.strip_prefix("\\\\?\\UNC\\") {
            return PathBuf::from(format!("\\\\{}", rest));
        }
        if let Some(rest) = path_string.strip_prefix("\\\\?\\") {
            return PathBuf::from(rest);
        }
    }

    path.to_path_buf()
}

fn find_executable(root: &Path, binary_name: &str) -> Option<PathBuf> {
    fn search(directory: &Path, target: &str, depth: usize) -> Option<PathBuf> {
        if depth > 3 {
            return None;
        }

        let entries = fs::read_dir(directory).ok()?;
        let mut subdirectories = Vec::new();

        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_file() {
                if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
                    if name.eq_ignore_ascii_case(target) {
                        return Some(path);
                    }
                }
            } else if path.is_dir() {
                subdirectories.push(path);
            }
        }

        for subdirectory in subdirectories {
            if let Some(found) = search(&subdirectory, target, depth + 1) {
                return Some(found);
            }
        }

        None
    }

    search(root, binary_name, 0)
}

fn parse_external_mod(line: &str) -> Option<&str> {
    let mut rest = line.trim();

    if let Some(after_pub) = rest.strip_prefix("pub") {
        let after_pub = after_pub.trim_start();
        if let Some(inner) = after_pub.strip_prefix('(') {
            let close = inner.find(')')?;
            rest = inner[close + 1..].trim_start();
        } else {
            rest = after_pub;
        }
    }

    let after_mod = rest.strip_prefix("mod")?;
    if !after_mod
        .chars()
        .next()
        .map_or(false, |character| character.is_whitespace())
    {
        return None;
    }

    let name = after_mod.trim().strip_suffix(';')?.trim();
    if name.is_empty() || !name.chars().all(|c| c.is_alphanumeric() || c == '_') {
        return None;
    }

    Some(name)
}

pub(crate) fn collect_rust_files(entry: &Path) -> Vec<PathBuf> {
    let entry_path = entry
        .canonicalize()
        .unwrap_or_else(|_| entry.to_path_buf());

    let mut visited: HashSet<PathBuf> = HashSet::new();
    let mut queue: VecDeque<PathBuf> = VecDeque::new();
    let mut files: Vec<PathBuf> = Vec::new();

    visited.insert(entry_path.clone());
    queue.push_back(entry_path);

    while let Some(current) = queue.pop_front() {
        files.push(current.clone());

        let contents = match fs::read_to_string(&current) {
            Ok(contents) => contents,
            Err(_) => continue,
        };

        let current_dir = match current.parent() {
            Some(parent) => parent,
            None => continue,
        };

        let is_mod_rs = current
            .file_name()
            .and_then(|name| name.to_str())
            .map(|name| name == "mod.rs")
            .unwrap_or(false);

        let stem_dir = if is_mod_rs {
            None
        } else {
            current
                .file_stem()
                .and_then(|stem| stem.to_str())
                .map(|stem| current_dir.join(stem))
        };

        for line in contents.lines() {
            let code = line.split("//").next().unwrap_or("");
            let name = match parse_external_mod(code) {
                Some(name) => name,
                None => continue,
            };

            let mut candidates = vec![
                current_dir.join(format!("{}.rs", name)),
                current_dir.join(name).join("mod.rs"),
            ];
            if let Some(stem_dir) = &stem_dir {
                candidates.push(stem_dir.join(format!("{}.rs", name)));
                candidates.push(stem_dir.join(name).join("mod.rs"));
            }

            for candidate in candidates {
                if !candidate.is_file() {
                    continue;
                }
                let resolved = candidate.canonicalize().unwrap_or(candidate);
                if visited.insert(resolved.clone()) {
                    queue.push_back(resolved);
                }
            }
        }
    }

    files = files.into_iter().map(|path| clean_path(&path)).collect();
    files.sort();
    files
}

fn parse_quoted_include(line: &str) -> Option<&str> {
    let after_hash = line.trim().strip_prefix('#')?;
    let after_hash = after_hash.trim_start();
    let after_include = after_hash.strip_prefix("include")?;
    let rest = after_include.trim_start();
    let rest = rest.strip_prefix('"')?;
    let end = rest.find('"')?;
    Some(&rest[..end])
}

pub(crate) fn collect_c_cpp_files(
    entry: &Path,
    is_cpp: bool,
) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let entry_path = entry
        .canonicalize()
        .unwrap_or_else(|_| entry.to_path_buf());

    let mut visited: HashSet<PathBuf> = HashSet::new();
    let mut queue: VecDeque<PathBuf> = VecDeque::new();
    let mut sources: Vec<PathBuf> = vec![entry_path.clone()];
    let mut all_files: Vec<PathBuf> = vec![entry_path.clone()];

    visited.insert(entry_path.clone());
    queue.push_back(entry_path);

    let implementation_extensions: &[&str] = if is_cpp {
        &[".cpp", ".cc", ".cxx", ".c"]
    } else {
        &[".c"]
    };

    while let Some(current) = queue.pop_front() {
        let contents = match fs::read_to_string(&current) {
            Ok(contents) => contents,
            Err(_) => continue,
        };

        let current_dir = match current.parent() {
            Some(parent) => parent,
            None => continue,
        };

        for line in contents.lines() {
            let code = line.split("//").next().unwrap_or("");
            let include = match parse_quoted_include(code) {
                Some(include) => include,
                None => continue,
            };

            let candidate = current_dir.join(include);
            if !candidate.is_file() {
                continue;
            }

            let resolved = candidate.canonicalize().unwrap_or(candidate);
            if !visited.insert(resolved.clone()) {
                continue;
            }

            all_files.push(resolved.clone());
            queue.push_back(resolved.clone());

            let is_header = resolved
                .extension()
                .and_then(|extension| extension.to_str())
                .map(|extension| extension.to_lowercase())
                .map(|extension| matches!(extension.as_str(), "h" | "hpp" | "hh" | "hxx"))
                .unwrap_or(false);

            if !is_header {
                continue;
            }

            let header_dir = match resolved.parent() {
                Some(parent) => parent,
                None => continue,
            };
            let stem = match resolved.file_stem().and_then(|stem| stem.to_str()) {
                Some(stem) => stem,
                None => continue,
            };

            for implementation_extension in implementation_extensions {
                let implementation =
                    header_dir.join(format!("{}{}", stem, implementation_extension));
                if !implementation.is_file() {
                    continue;
                }
                let implementation = implementation
                    .canonicalize()
                    .unwrap_or(implementation);
                if visited.insert(implementation.clone()) {
                    sources.push(implementation.clone());
                    all_files.push(implementation.clone());
                    queue.push_back(implementation);
                }
                break;
            }
        }
    }

    sources = sources.into_iter().map(|path| clean_path(&path)).collect();
    all_files = all_files
        .into_iter()
        .map(|path| clean_path(&path))
        .collect();
    sources.sort();
    all_files.sort();
    (sources, all_files)
}

fn execute_binary(binary: &Path, program_args: &[String]) -> i32 {
    match Command::new(binary)
        .args(program_args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()
    {
        Ok(status) => status.code().unwrap_or(1),
        Err(error) => {
            eprintln!("Failed to execute binary: {}", error);
            1
        }
    }
}

fn run_bun(file_path: &str, program_args: &[String], toolchains_dir: &Path) -> i32 {
    let binary_name = if cfg!(windows) { "bun.exe" } else { "bun" };
    let bun_root = toolchains_dir.join("bun");
    let bun = match find_executable(&bun_root, binary_name) {
        Some(path) => path,
        None => {
            eprintln!("JS/TS toolchain not installed. Run 'hlowld' to install it.");
            return 1;
        }
    };

    match Command::new(&bun)
        .arg("run")
        .arg(file_path)
        .args(program_args)
        .env("BUN_INSTALL", &bun_root)
        .env("BUN_INSTALL_CACHE_DIR", bun_root.join("cache"))
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()
    {
        Ok(status) => status.code().unwrap_or(1),
        Err(error) => {
            eprintln!("Failed to run Bun: {}", error);
            1
        }
    }
}

fn run_zig(
    file_path: &str,
    program_args: &[String],
    toolchains_dir: &Path,
    cache_dir: &Path,
    extension: &str,
    raw_errors: bool,
) -> i32 {
    let binary_name = if cfg!(windows) { "zig.exe" } else { "zig" };
    let zig_root = toolchains_dir.join("zig");
    let zig = match find_executable(&zig_root, binary_name) {
        Some(path) => path,
        None => {
            eprintln!("C/C++ toolchain not installed. Run 'hlowld' to install it.");
            return 1;
        }
    };
    let zig_cache_dir = zig_root.join("cache");

    let entry_parent = match Path::new(file_path).canonicalize() {
        Ok(path) => path
            .parent()
            .map(clean_path)
            .unwrap_or_else(|| PathBuf::from(".")),
        Err(_) => PathBuf::from("."),
    };

    let is_cpp = extension == "cpp";
    let (sources, all_files) = collect_c_cpp_files(Path::new(file_path), is_cpp);

    let mut flags: Vec<String> = Vec::new();
    if is_cpp {
        flags.push("-std=c++20".to_string());
    }

    let mut hasher = Sha256::new();
    let mut has_math = false;
    let mut has_pthread = false;

    for dependency in &all_files {
        hasher.update(dependency.to_string_lossy().as_bytes());
        match fs::read(dependency) {
            Ok(bytes) => {
                let text = String::from_utf8_lossy(&bytes);
                if text.contains("<math.h>") {
                    has_math = true;
                }
                if text.contains("<pthread.h>") {
                    has_pthread = true;
                }
                hasher.update(&bytes);
            }
            Err(error) => {
                eprintln!("Failed to read source file: {}", error);
                return 1;
            }
        }
    }

    if !is_cpp {
        if has_math {
            flags.push("-lm".to_string());
        }
        if has_pthread {
            flags.push("-lpthread".to_string());
        }
    }

    let subcommand = if is_cpp { "c++" } else { "cc" };
    let hash = hex::encode(hasher.finalize());

    let mut cached_binary = cache_dir.join(hash);
    if cfg!(windows) {
        cached_binary.set_extension("exe");
    }

    if !cached_binary.exists() {
        let mut command = Command::new(&zig);
        command.arg(subcommand);
        command.arg("-I");
        command.arg(&entry_parent);
        for source_file in &sources {
            command.arg(source_file);
        }
        command
            .arg("-o")
            .arg(&cached_binary)
            .args(&flags)
            .env("ZIG_GLOBAL_CACHE_DIR", &zig_cache_dir)
            .env("ZIG_LOCAL_CACHE_DIR", &zig_cache_dir)
            .stdin(Stdio::inherit());

        match command.output() {
            Ok(output) if output.status.success() => {
                if !output.stderr.is_empty() {
                    eprint!("{}", String::from_utf8_lossy(&output.stderr));
                }
            }
            Ok(output) => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                if raw_errors {
                    eprint!("{}", stderr);
                } else {
                    println!(
                        "{}",
                        crate::errors::format_compiler_error(
                            extension,
                            &stderr,
                            Path::new(file_path)
                        )
                    );
                    println!("\x1b[2m(run with --raw to see full compiler output)\x1b[0m");
                }
                return output.status.code().unwrap_or(1);
            }
            Err(error) => {
                eprintln!("Failed to run Zig: {}", error);
                return 1;
            }
        }
    }

    execute_binary(&cached_binary, program_args)
}

fn run_rust(
    file_path: &str,
    program_args: &[String],
    toolchains_dir: &Path,
    cache_dir: &Path,
    raw_errors: bool,
) -> i32 {
    let binary_name = if cfg!(windows) { "rustc.exe" } else { "rustc" };
    let rust_root = toolchains_dir.join("rust");
    let rustc = match find_executable(&rust_root, binary_name) {
        Some(path) => path,
        None => {
            eprintln!("Rust toolchain not installed. Run 'hlowld' to install it.");
            return 1;
        }
    };
    let rustup_home = {
        let candidate = rust_root.join("rustup");
        if candidate.exists() {
            candidate
        } else {
            rust_root.clone()
        }
    };
    let cargo_home = {
        let candidate = rust_root.join("cargo");
        if candidate.exists() {
            candidate
        } else {
            rust_root.clone()
        }
    };

    let rust_files = collect_rust_files(Path::new(file_path));
    let mut hasher = Sha256::new();
    for module_file in &rust_files {
        hasher.update(module_file.to_string_lossy().as_bytes());
        match fs::read(module_file) {
            Ok(bytes) => hasher.update(&bytes),
            Err(error) => {
                eprintln!("Failed to read source file: {}", error);
                return 1;
            }
        }
    }
    let hash = hex::encode(hasher.finalize());

    let mut cached_binary = cache_dir.join(hash);
    if cfg!(windows) {
        cached_binary.set_extension("exe");
    }

    if !cached_binary.exists() {
        let output = Command::new(&rustc)
            .arg(file_path)
            .arg("-o")
            .arg(&cached_binary)
            .env("RUSTUP_HOME", &rustup_home)
            .env("CARGO_HOME", &cargo_home)
            .stdin(Stdio::inherit())
            .output();

        match output {
            Ok(output) if output.status.success() => {
                if !output.stderr.is_empty() {
                    eprint!("{}", String::from_utf8_lossy(&output.stderr));
                }
            }
            Ok(output) => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                if raw_errors {
                    eprint!("{}", stderr);
                } else {
                    println!(
                        "{}",
                        crate::errors::format_compiler_error(
                            "rust",
                            &stderr,
                            Path::new(file_path)
                        )
                    );
                    println!("\x1b[2m(run with --raw to see full compiler output)\x1b[0m");
                }
                return output.status.code().unwrap_or(1);
            }
            Err(error) => {
                eprintln!("Failed to run rustc: {}", error);
                return 1;
            }
        }
    }

    execute_binary(&cached_binary, program_args)
}
