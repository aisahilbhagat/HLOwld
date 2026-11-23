use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use sha2::{Digest, Sha256};

pub fn run_file(file_path: &str, program_args: &[String]) -> i32 {
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
        ),
        "rs" => run_rust(file_path, program_args, &toolchains_dir, &cache_dir),
        _ => {
            eprintln!("Unsupported extension. Supported: .c, .cpp, .rs, .ts, .js");
            1
        }
    }
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
    let bun = match find_executable(&toolchains_dir.join("bun"), binary_name) {
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
) -> i32 {
    let binary_name = if cfg!(windows) { "zig.exe" } else { "zig" };
    let zig = match find_executable(&toolchains_dir.join("zig"), binary_name) {
        Some(path) => path,
        None => {
            eprintln!("C/C++ toolchain not installed. Run 'hlowld' to install it.");
            return 1;
        }
    };

    let source = match fs::read_to_string(file_path) {
        Ok(contents) => contents,
        Err(error) => {
            eprintln!("Failed to read source file: {}", error);
            return 1;
        }
    };

    let (subcommand, flags): (&str, Vec<String>) = if extension == "c" {
        let mut flags = Vec::new();
        if source.contains("<math.h>") {
            flags.push("-lm".to_string());
        }
        if source.contains("<pthread.h>") {
            flags.push("-lpthread".to_string());
        }
        ("cc", flags)
    } else {
        ("c++", vec!["-std=c++20".to_string()])
    };

    let mut hasher = Sha256::new();
    hasher.update(source.as_bytes());
    hasher.update(extension.as_bytes());
    for flag in &flags {
        hasher.update(flag.as_bytes());
    }
    let hash = hex::encode(hasher.finalize());

    let mut cached_binary = cache_dir.join(hash);
    if cfg!(windows) {
        cached_binary.set_extension("exe");
    }

    if !cached_binary.exists() {
        let status = Command::new(&zig)
            .arg(subcommand)
            .arg(file_path)
            .arg("-o")
            .arg(&cached_binary)
            .args(&flags)
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .status();

        match status {
            Ok(status) if status.success() => {}
            Ok(status) => return status.code().unwrap_or(1),
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

    let source = match fs::read_to_string(file_path) {
        Ok(contents) => contents,
        Err(error) => {
            eprintln!("Failed to read source file: {}", error);
            return 1;
        }
    };

    let mut hasher = Sha256::new();
    hasher.update(source.as_bytes());
    let hash = hex::encode(hasher.finalize());

    let mut cached_binary = cache_dir.join(hash);
    if cfg!(windows) {
        cached_binary.set_extension("exe");
    }

    if !cached_binary.exists() {
        let status = Command::new(&rustc)
            .arg(file_path)
            .arg("-o")
            .arg(&cached_binary)
            .env("RUSTUP_HOME", rust_root.join("rustup"))
            .env("CARGO_HOME", rust_root.join("cargo"))
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .status();

        match status {
            Ok(status) if status.success() => {}
            Ok(status) => return status.code().unwrap_or(1),
            Err(error) => {
                eprintln!("Failed to run rustc: {}", error);
                return 1;
            }
        }
    }

    execute_binary(&cached_binary, program_args)
}
