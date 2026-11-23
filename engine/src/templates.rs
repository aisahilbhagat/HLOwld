use std::fs;
use std::path::Path;

pub fn create_template(file_path: &str) -> Result<(), String> {
    if Path::new(file_path).exists() {
        return Err("File already exists. Refusing to overwrite.".to_string());
    }

    let extension = Path::new(file_path)
        .extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.to_lowercase())
        .unwrap_or_default();

    let content = match extension.as_str() {
        "c" => {
            "#include <stdio.h>\n\nint main(void) {\n    printf(\"Hello, world!\\n\");\n    return 0;\n}\n"
        }
        "cpp" => {
            "#include <iostream>\n\nint main() {\n    std::cout << \"Hello, world!\\n\";\n    return 0;\n}\n"
        }
        "rs" => "fn main() {\n    println!(\"Hello, world!\");\n}\n",
        "ts" => "const msg: string = \"Hello, world!\";\nconsole.log(msg);\n",
        "js" => "console.log(\"Hello, world!\");\n",
        _ => {
            return Err(
                "Unsupported extension. Supported: .c, .cpp, .rs, .ts, .js".to_string(),
            )
        }
    };

    fs::write(file_path, content).map_err(|e| format!("Failed to create file: {}", e))?;
    println!("Created {}", file_path);
    Ok(())
}
