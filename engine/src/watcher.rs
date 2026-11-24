use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, SystemTime};

use crate::runner;

pub fn watch_and_run(entry: &Path, args: &[String], raw_errors: bool) -> i32 {
    if !entry.exists() {
        eprintln!("Error: file not found: {}", entry.display());
        return 1;
    }

    let entry_string = entry.to_string_lossy().into_owned();
    let entry_name = entry
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| entry_string.clone());

    let mut files = tracked_files(entry);
    let mut state = snapshot(&files);

    loop {
        print!("\x1B[2J\x1B[1;1H");
        println!("[hlowld watch] Running {}... (Ctrl+C to stop)", entry_name);
        let _ = std::io::stdout().flush();

        runner::run_file(&entry_string, args, raw_errors);

        loop {
            thread::sleep(Duration::from_millis(250));
            let latest = snapshot(&files);
            if latest != state {
                files = tracked_files(entry);
                state = snapshot(&files);
                break;
            }
        }
    }
}

fn tracked_files(entry: &Path) -> Vec<PathBuf> {
    let extension = entry
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.to_lowercase())
        .unwrap_or_default();

    match extension.as_str() {
        "rs" => runner::collect_rust_files(entry),
        "c" | "cpp" => runner::collect_c_cpp_files(entry, extension == "cpp").1,
        _ => vec![entry.to_path_buf()],
    }
}

fn snapshot(files: &[PathBuf]) -> Vec<(PathBuf, Option<SystemTime>)> {
    files
        .iter()
        .map(|file| {
            let modified = fs::metadata(file)
                .and_then(|metadata| metadata.modified())
                .ok();
            (file.clone(), modified)
        })
        .collect()
}
