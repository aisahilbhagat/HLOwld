"""Language toolchain installation and removal for hlowld."""

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
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
from rich.status import Status

from hlowld.config import BASE_DIR, LANGUAGES, TOOLCHAINS_DIR, STATE_FILE, load_state, save_state

console = Console()

CACHE_DIR = BASE_DIR / "cache"


def safe_rmtree(path: Path) -> None:
    """Remove a directory tree, clearing read-only attributes and retrying."""

    def _on_error(func, failed_path, exc_info):
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            func(failed_path)
        except OSError:
            try:
                os.chmod(failed_path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                func(failed_path)
            except OSError:
                pass

    target = Path(path)
    if target.exists():
        shutil.rmtree(target, onerror=_on_error)


def get_installed_languages() -> list[str]:
    """Return language keys that are installed and whose folder exists on disk."""
    state = load_state()
    installed: list[str] = []
    for lang_key, info in LANGUAGES.items():
        folder = TOOLCHAINS_DIR / info["folder"]
        if lang_key in state and folder.exists():
            installed.append(lang_key)
    return installed


def get_dir_size(path: Path) -> int:
    """Return the total size in bytes of a directory tree, ignoring errors."""
    target = Path(path)
    if not target.exists():
        return 0

    total = 0
    for root, _dirs, files in os.walk(target, onerror=lambda _error: None):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def clean_caches() -> tuple[int, list[str]]:
    """Delete hlowld-managed caches and return (bytes freed, cleaned labels)."""
    targets = [
        (CACHE_DIR, "binary cache"),
        (TOOLCHAINS_DIR / "zig" / "cache", "zig cache"),
        (TOOLCHAINS_DIR / "bun" / "cache", "bun cache"),
        (
            TOOLCHAINS_DIR / "rust" / "cargo" / "registry" / "cache",
            "cargo registry cache",
        ),
        (TOOLCHAINS_DIR / "rust" / "cargo" / "git", "cargo git cache"),
    ]

    bytes_freed = 0
    cleaned: list[str] = []

    for target, label in targets:
        if not target.exists():
            continue
        bytes_freed += get_dir_size(target)
        safe_rmtree(target)
        cleaned.append(label)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return bytes_freed, cleaned


def clean_file_cache(file_path: str) -> tuple[bool, int]:
    """Delete the cached binary matching a source file's SHA-256, if present."""
    source = Path(file_path)
    if not source.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    hasher = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 64), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()

    if not CACHE_DIR.exists():
        return False, 0

    matches = list(CACHE_DIR.glob(f"{digest}*"))
    removed = False
    bytes_freed = 0

    for match in matches:
        try:
            if match.is_file():
                size = match.stat().st_size
                match.unlink()
                bytes_freed += size
                removed = True
            elif match.is_dir():
                bytes_freed += get_dir_size(match)
                safe_rmtree(match)
                removed = True
        except OSError:
            continue

    if not removed:
        return False, 0
    return True, bytes_freed


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
    safe_rmtree(folder)


def _find_binary(root: Path, binary_name: str) -> Path | None:
    for candidate in root.rglob(binary_name):
        if candidate.is_file():
            return candidate
    return None


def _warm_up_zig(zig_bin: Path) -> None:
    zig_cache_dir = TOOLCHAINS_DIR / "zig" / "cache"
    zig_cache_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ZIG_GLOBAL_CACHE_DIR"] = str(zig_cache_dir)
    env["ZIG_LOCAL_CACHE_DIR"] = str(zig_cache_dir)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        warmup_c = tmp_path / "warmup.c"
        warmup_cpp = tmp_path / "warmup.cpp"
        warmup_c.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        warmup_cpp.write_text(
            "#include <iostream>\nint main() { return 0; }\n", encoding="utf-8"
        )
        c_output = tmp_path / ("warmup-c.exe" if sys.platform == "win32" else "warmup-c")
        cpp_output = tmp_path / (
            "warmup-cpp.exe" if sys.platform == "win32" else "warmup-cpp"
        )

        try:
            with Status(
                "Warming up C & C++ compiler caches (one-time setup)...",
                console=console,
            ):
                subprocess.run(
                    [str(zig_bin), "cc", str(warmup_c), "-o", str(c_output)],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    [
                        str(zig_bin),
                        "c++",
                        "-std=c++20",
                        str(warmup_cpp),
                        "-o",
                        str(cpp_output),
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:  # noqa: BLE001
            pass


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
                if success:
                    zig_name = "zig.exe" if sys.platform == "win32" else "zig"
                    zig_bin = _find_binary(folder, zig_name)
                    if zig_bin is not None:
                        if sys.platform != "win32":
                            os.chmod(zig_bin, 0o755)
                        _warm_up_zig(zig_bin)
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
                if success and sys.platform != "win32":
                    bun_bin = _find_binary(folder, "bun")
                    if bun_bin is not None:
                        os.chmod(bun_bin, 0o755)
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
    safe_rmtree(folder)
    safe_rmtree(CACHE_DIR)

    state = load_state()
    state.pop(lang_key, None)
    save_state(state)
    console.print(f"[yellow]Removed {info['display']}[/yellow]")
    return True


def uninstall_all() -> bool:
    """Remove the entire ~/.hlowld directory."""
    safe_rmtree(BASE_DIR)
    return True
