"""OS/arch detection and isolated path/state management for hlowld."""

import json
import platform
from pathlib import Path

SUPPORTED_OS = {"Windows", "Linux"}

UNSUPPORTED_MSG = "Unsupported OS. hlowld only supports Windows and Linux."


def check_os() -> None:
    """Exit with code 1 if the current OS is not Windows or Linux."""
    if platform.system() not in SUPPORTED_OS:
        print(UNSUPPORTED_MSG)
        raise SystemExit(1)


def detect_arch() -> str:
    """Return a normalized architecture string: 'x86_64' or 'aarch64'."""
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine


BASE_DIR = Path.home() / ".hlowld"
TOOLCHAINS_DIR = BASE_DIR / "toolchains"
STATE_FILE = BASE_DIR / "state.json"

LANGUAGES = {
    "c_cpp": {
        "display": "C / C++ (Zig Toolchain)",
        "folder": "zig",
    },
    "rust": {
        "display": "Rust (rustc + cargo)",
        "folder": "rust",
    },
    "js_ts": {
        "display": "JavaScript / TypeScript (Bun)",
        "folder": "bun",
    },
}


def _ensure_dirs() -> None:
    """Auto-create BASE_DIR and TOOLCHAINS_DIR if missing."""
    TOOLCHAINS_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    """Read state.json, auto-creating directories if missing."""
    _ensure_dirs()
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    """Write state to state.json, auto-creating directories if missing."""
    _ensure_dirs()
    tmp_file = STATE_FILE.with_suffix(".json.tmp")
    with tmp_file.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    tmp_file.replace(STATE_FILE)
