<div align="center">

# ⚡ hlowld

**Run Rust, C, C++, TypeScript, and JavaScript like Python — zero config, zero boilerplate.**

[![Status](https://img.shields.io/badge/status-alpha%20%2F%20in%20development-orange?style=for-the-badge)]()
[![Platform](https://img.shields.io/badge/platform-Windows%20(Verified)%20%7C%20Linux%20(WIP)-blue?style=for-the-badge)]()
[![Engine](https://img.shields.io/badge/engine-Rust-DEA584?style=for-the-badge&logo=rust&logoColor=black)]()
[![CLI](https://img.shields.io/badge/CLI-Python%203.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)]()

*Sandboxed toolchains • Smart SHA-256 caching • Auto multi-file linking • Python-style error tracebacks • Live watch mode*

</div>

---

> [!WARNING]
> **Early Development (Alpha):** `hlowld` is actively being built and is **not production-ready yet**. It is currently tested and verified on **Windows**. Linux support is written in, but native Linux testing and CI are still on the roadmap.

---

## ✨ Why `hlowld`?

Writing a quick script in Rust or C++ usually means fighting `Cargo.toml`, `CMakeLists.txt`, linkers, and system `PATH`s. `hlowld` gives compiled languages the same instant `python file.py` experience:

```bash
hlowld main.rs        # Compiles, caches, and runs Rust
hlowld main.cpp       # Auto-links local #include files via Zig C++20
hlowld app.ts         # Runs TypeScript/JavaScript natively via Bun