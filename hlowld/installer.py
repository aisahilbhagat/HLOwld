"""Language toolchain installation and removal for hlowld."""

import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from hlowld.config import BASE_DIR, LANGUAGES, TOOLCHAINS_DIR, STATE_FILE, load_state, save_state

console = Console()


def _on_rm_error(func, path, exc_info):
    """Handle Windows read-only files during rmtree."""
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    else:
        raise


def get_installed_languages() -> list[str]:
    """Return language keys that are installed and whose folder exists on disk."""
    state = load_state()
    installed: list[str] = []
    for lang_key, info in LANGUAGES.items():
        folder = TOOLCHAINS_DIR / info["folder"]
        if lang_key in state and folder.exists():
            installed.append(lang_key)
    return installed


def _download(url: str, dest: Path) -> bool:
    """Stream url to dest with a visible rich progress bar. Returns True on success."""
    console.print(f"[cyan]Downloading from:[/cyan] {url}")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "hlowld/0.1.0"})
        with urllib.request.urlopen(request) as response:
            total = int(response.headers.get("Content-Length", 0) or 0)
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=False,
            ) as progress:
                task = progress.add_task("Downloading", total=total or None)
                with dest.open("wb") as out_file:
                    while True:
                        chunk = response.read(1024 * 64)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        progress.update(task, advance=len(chunk))
        return True
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Download failed: {exc}[/red]")
        return False


def _extract_zip(archive: Path, dest_dir: Path) -> bool:
    console.print(f"[cyan]Extracting to:[/cyan] {dest_dir}")
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
        return True
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Extraction failed: {exc}[/red]")
        return False


def _extract_tar(archive: Path, dest_dir: Path) -> bool:
    console.print(f"[cyan]Extracting to:[/cyan] {dest_dir}")
    try:
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(dest_dir)
        return True
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Extraction failed: {exc}[/red]")
        return False


def _cleanup_folder(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder, onerror=_on_rm_error)


def _zig_url() -> str:
    arch = "x86_64"  # portable zig releases target x86_64
    if sys.platform == "win32":
        return "https://ziglang.org/download/0.13.0/zig-windows-x86_64-0.13.0.zip"
    return "https://ziglang.org/download/0.13.0/zig-linux-x86_64-0.13.0.tar.xz"


def _rustup_url() -> str:
    if sys.platform == "win32":
        return "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe"
    return "https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init"


def _bun_url() -> str:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "https://github.com/oven-sh/bun/releases/download/bun-v1.1.20/bun-windows-x64.zip"
    if machine in {"arm64", "aarch64"}:
        return "https://github.com/oven-sh/bun/releases/download/bun-v1.1.20/bun-linux-aarch64.zip"
    return "https://github.com/oven-sh/bun/releases/download/bun-v1.1.20/bun-linux-x64.zip"


def install_language(lang_key: str) -> bool:
    """Install a language toolchain into ~/.hlowld/toolchains/<folder>/."""
    if lang_key not in LANGUAGES:
        console.print(f"[red]Unknown language:[/red] {lang_key}")
        return False

    info = LANGUAGES[lang_key]
    display = info["display"]
    folder = TOOLCHAINS_DIR / info["folder"]
    folder.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold cyan]Installing {display}...[/bold cyan]")
    success = False
    try:
        if lang_key == "c_cpp":
            url = _zig_url()
            archive = BASE_DIR / f"zig-archive{'.zip' if sys.platform == 'win32' else '.tar.xz'}"
            if _download(url, archive):
                if sys.platform == "win32":
                    success = _extract_zip(archive, folder)
                else:
                    success = _extract_tar(archive, folder)
            archive.unlink(missing_ok=True)

        elif lang_key == "rust":
            url = _rustup_url()
            archive = BASE_DIR / ("rustup-init.exe" if sys.platform == "win32" else "rustup-init")
            if _download(url, archive):
                if sys.platform != "win32":
                    os.chmod(archive, 0o755)
                rustup_home = folder / "rustup"
                cargo_home = folder / "cargo"
                env = os.environ.copy()
                env["RUSTUP_HOME"] = str(rustup_home)
                env["CARGO_HOME"] = str(cargo_home)
                rustup_args = [str(archive), "-y", "--no-modify-path"]
                if (
                    sys.platform == "win32"
                    and platform.machine().lower() in {"amd64", "x86_64"}
                ):
                    rustup_args.extend(["--default-host", "x86_64-pc-windows-gnu"])
                console.print(f"[cyan]Running rustup-init for {display}...[/cyan]")
                result = subprocess.run(rustup_args, env=env)
                success = result.returncode == 0
                if not success:
                    console.print(
                        f"[red]rustup-init exited with code {result.returncode}.[/red]"
                    )
            archive.unlink(missing_ok=True)

        elif lang_key == "js_ts":
            url = _bun_url()
            archive = BASE_DIR / "bun-archive.zip"
            if _download(url, archive):
                success = _extract_zip(archive, folder)
            archive.unlink(missing_ok=True)

        if success:
            state = load_state()
            state[lang_key] = str(folder)
            save_state(state)
            console.print(f"[green]Successfully installed {display}.[/green]")
        else:
            _cleanup_folder(folder)
            console.print(f"[red]Failed to install {display}.[/red]")
    except Exception as e:  # noqa: BLE001
        _cleanup_folder(folder)
        console.print(f"[red]Installation failed: {e}[/red]")
        success = False

    return success


def uninstall_language(lang_key: str) -> bool:
    """Remove a language toolchain folder and its state entry."""
    if lang_key not in LANGUAGES:
        console.print(f"[red]Unknown language:[/red] {lang_key}")
        return False

    info = LANGUAGES[lang_key]
    folder = TOOLCHAINS_DIR / info["folder"]
    _cleanup_folder(folder)

    state = load_state()
    state.pop(lang_key, None)
    save_state(state)
    console.print(f"[yellow]Removed {info['display']}[/yellow]")
    return True
