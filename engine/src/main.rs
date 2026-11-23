mod runner;
mod templates;

use std::env;
use std::process;

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        println!("Usage: hlowld-engine new <file> | hlowld-engine <file> [args...]");
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

    let exit_code = runner::run_file(&args[0], &args[1..]);
    process::exit(exit_code);
}
