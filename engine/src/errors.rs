use std::fmt::Write;
use std::fs;
use std::path::{Path, PathBuf};

struct ParsedError {
    file: String,
    line: usize,
    column: usize,
    message: String,
}

pub fn format_compiler_error(lang: &str, stderr: &str, source_fallback: &Path) -> String {
    let parsed = if lang.eq_ignore_ascii_case("rust") {
        parse_rust_error(stderr)
    } else {
        parse_clang_error(stderr)
    };

    let Some(error) = parsed else {
        return stderr.to_string();
    };

    let source_path = resolve_source_path(&error.file, source_fallback);
    let source_line = read_source_line(&source_path, error.line);

    let mut output = String::new();
    let _ = writeln!(
        output,
        "\x1b[1;31mTraceback (most recent call last):\x1b[0m"
    );
    let _ = writeln!(
        output,
        "  \x1b[36mFile \"{}\", line {}\x1b[0m",
        error.file, error.line
    );
    if let Some(text) = &source_line {
        let _ = writeln!(output, "    {}", text.trim_end());
        let carets = error
            .column
            .saturating_sub(1)
            .min(text.chars().count());
        let _ = writeln!(output, "    {}^", " ".repeat(carets));
    }
    let _ = writeln!(output, "\x1b[1;31mError:\x1b[0m {}", error.message);
    if let Some(hint) = hint_for(&error.message) {
        let _ = writeln!(output, "\x1b[1;33mHint:\x1b[0m {}", hint);
    }

    output.trim_end().to_string()
}

fn parse_clang_error(stderr: &str) -> Option<ParsedError> {
    for line in stderr.lines() {
        let trimmed = line.trim_start();

        let (location, message) = if let Some(index) = trimmed.find(": fatal error: ") {
            (
                &trimmed[..index],
                &trimmed[index + ": fatal error: ".len()..],
            )
        } else if let Some(index) = trimmed.find(": error: ") {
            (&trimmed[..index], &trimmed[index + ": error: ".len()..])
        } else {
            continue;
        };

        let Some((file, line_number, column)) = parse_location(location) else {
            continue;
        };

        return Some(ParsedError {
            file,
            line: line_number,
            column,
            message: message.trim().to_string(),
        });
    }

    None
}

fn parse_rust_error(stderr: &str) -> Option<ParsedError> {
    let lines: Vec<&str> = stderr.lines().collect();

    for (index, line) in lines.iter().enumerate() {
        let trimmed = line.trim_start();

        let message = if let Some(rest) = trimmed.strip_prefix("error[") {
            rest.find("]: ")
                .map(|position| rest[position + 3..].trim().to_string())
        } else if let Some(rest) = trimmed.strip_prefix("error: ") {
            Some(rest.trim().to_string())
        } else {
            None
        };

        let Some(message) = message else {
            continue;
        };

        for candidate in &lines[index + 1..] {
            let candidate = candidate.trim_start();
            if candidate.starts_with("error[") || candidate.starts_with("error: ") {
                break;
            }
            if let Some(location) = candidate.strip_prefix("--> ") {
                if let Some((file, line_number, column)) = parse_location(location.trim()) {
                    return Some(ParsedError {
                        file,
                        line: line_number,
                        column,
                        message,
                    });
                }
            }
        }
    }

    None
}

fn parse_location(location: &str) -> Option<(String, usize, usize)> {
    let mut parts = location.rsplitn(3, ':');
    let column = parts.next()?.trim().parse::<usize>().ok()?;
    let line = parts.next()?.trim().parse::<usize>().ok()?;
    let file = parts.next()?.trim().to_string();

    if file.is_empty() {
        return None;
    }

    Some((file, line, column))
}

fn resolve_source_path(file: &str, source_fallback: &Path) -> PathBuf {
    let candidate = PathBuf::from(file);
    if candidate.exists() {
        return candidate;
    }

    if candidate.is_relative() {
        if let Some(parent) = source_fallback.parent() {
            let joined = parent.join(file);
            if joined.exists() {
                return joined;
            }
        }
    }

    candidate
}

fn read_source_line(path: &Path, line: usize) -> Option<String> {
    if line == 0 {
        return None;
    }

    let contents = fs::read_to_string(path).ok()?;
    contents
        .lines()
        .nth(line - 1)
        .map(|text| text.to_string())
}

fn hint_for(message: &str) -> Option<&'static str> {
    let message = message.to_lowercase();

    if message.contains("expected ';'") || message.contains("expected `;`") {
        Some("A semicolon is missing at the end of this statement.")
    } else if message.contains("cannot assign twice to immutable variable") {
        Some("Declare the binding as mutable with `let mut` to allow reassignment.")
    } else if message.contains("use of undeclared") || message.contains("cannot find value") {
        Some("Check for a typo, or declare the variable before using it.")
    } else if message.contains("mismatched types") || message.contains("incompatible type") {
        Some("Make sure both values use the same type, or convert one explicitly.")
    } else if message.contains("undefined reference") {
        Some("A symbol is declared but never defined, or a required library is missing from the link step.")
    } else {
        None
    }
}
