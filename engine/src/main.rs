mod errors;
mod runner;
mod templates;
mod watcher;

use std::env;
use std::path::Path;
use std::process;

fn main() {
    let mut args: Vec<String> = env::args().skip(1).collect();
    let mut raw_errors = false;

    if args.first().map_or(false, |arg| arg == "--raw") {
        raw_errors = true;
        args.remove(0);
    }

    if args.is_empty() {
        println!(
            "Usage: hlowld-engine new <file> | hlowld-engine [--raw] <file> [args...] | hlowld-engine watch [--raw] <file> [args...]"
        );
        process::exit(1);
    }

    if args[0] == "new" {
        if args.len() < 2 {
            println!("Usage: hlowld-engine new <file>");
            process::exit(1);
        }

        match templates::create_template(&args[1]) {
            Ok(()) => process::exit(0),
            Err(message) => {
                eprintln!("{}", message);
                process::exit(1);
            }
        }
    }

    if args[0] == "watch" {
        let mut watch_args = &args[1..];
        if watch_args.first().map_or(false, |arg| arg == "--raw") {
            raw_errors = true;
            watch_args = &watch_args[1..];
        }
        if watch_args.is_empty() {
            println!("Usage: hlowld-engine watch [--raw] <file> [args...]");
            process::exit(1);
        }

        let exit_code =
            watcher::watch_and_run(Path::new(&watch_args[0]), &watch_args[1..], raw_errors);
        process::exit(exit_code);
    }

    let exit_code = runner::run_file(&args[0], &args[1..], raw_errors);
    process::exit(exit_code);
}
