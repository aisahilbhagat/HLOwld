"""Interactive CLI entry point for hlowld."""

import subprocess
import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hlowld.config import LANGUAGES, check_os
from hlowld.installer import (
    clean_caches,
    clean_file_cache,
    get_installed_languages,
    install_language,
    uninstall_all,
    uninstall_language,
)

console = Console()


def _header() -> None:
    console.print(
        Panel.fit("hlowld v0.1.0 — Portable Language Manager", style="bold cyan")
    )


def _status_table() -> None:
    installed = set(get_installed_languages())
    table = Table(title="Installed Language Status", show_lines=True)
    table.add_column("Language", style="cyan", no_wrap=True)
    table.add_column("Status", style="green", no_wrap=True)
    table.add_column("Folder", style="magenta")

    from hlowld.config import BASE_DIR, TOOLCHAINS_DIR

    for lang_key, info in LANGUAGES.items():
        folder = TOOLCHAINS_DIR / info["folder"]
        is_installed = lang_key in installed
        table.add_row(
            info["display"],
            "Installed" if is_installed else "Not Installed",
            str(folder),
        )
    console.print(table)


def _find_engine_binary() -> Path | None:
    exe_name = "hlowld-engine.exe" if sys.platform == "win32" else "hlowld-engine"
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / "engine" / "target" / "release" / exe_name,
        Path.home() / ".hlowld" / "bin" / exe_name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _run_engine(args: list[str]) -> None:
    engine_bin = _find_engine_binary()
    if engine_bin is None:
        console.print(
            "[red]Rust engine not built yet. Run: cd engine && cargo build --release[/red]"
        )
        sys.exit(1)

    try:
        result = subprocess.run([str(engine_bin), *args])
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(result.returncode)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _print_cache_clean_result(bytes_freed: int, cleaned: list[str]) -> None:
    if bytes_freed == 0:
        console.print("[green]Already clean (0 MB freed).[/green]")
        return
    labels = ", ".join(cleaned) if cleaned else "cache"
    console.print(
        f"[green]Cleaned {_format_size(bytes_freed)} across: {labels}[/green]"
    )


def _clean_command(args: list[str]) -> None:
    if "--all" in args:
        assume_yes = any(arg in {"-y", "--yes"} for arg in args)
        if not assume_yes:
            assume_yes = bool(
                questionary.confirm(
                    "Remove ~/.hlowld and all installed toolchains?"
                ).ask()
            )
        if not assume_yes:
            console.print("[yellow]Clean reset cancelled.[/yellow]")
            return
        uninstall_all()
        console.print("[green]Removed ~/.hlowld and all installed toolchains.[/green]")
        return

    positional = [arg for arg in args if arg not in {"-y", "--yes"}]
    if not positional:
        bytes_freed, cleaned = clean_caches()
        _print_cache_clean_result(bytes_freed, cleaned)
        return

    filename = positional[0]
    try:
        removed, bytes_freed = clean_file_cache(filename)
    except FileNotFoundError:
        console.print(f"[red]File not found: {filename}[/red]")
        sys.exit(1)
    except OSError as exc:
        console.print(f"[red]Failed to clean cache: {exc}[/red]")
        sys.exit(1)

    if removed:
        console.print(
            f"[green]Cleared cached binary for {filename} ({_format_size(bytes_freed)})[/green]"
        )
    else:
        console.print(f"[yellow]No cached binary found for {filename}.[/yellow]")


def main() -> None:
    check_os()

    cli_args = sys.argv[1:]
    if cli_args:
        if cli_args[0] == "clean":
            _clean_command(cli_args[1:])
            sys.exit(0)
        _run_engine(cli_args)

    _header()

    while True:
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                "Install languages",
                "Remove languages",
                "View installed status",
                "Clean Caches (Free Disk Space)",
                "Uninstall Everything (Clean Reset)",
                "Exit",
            ],
        ).ask()

        if choice is None:
            # Ctrl+C / user aborted the select
            console.print("\n[yellow]Exiting.[/yellow]")
            break

        if choice == "Install languages":
            installed = set(get_installed_languages())
            choices = []
            for lang_key, info in LANGUAGES.items():
                label = info["display"]
                if lang_key in installed:
                    label = f"{label} [Installed]"
                    choices.append(questionary.Choice(title=label, value=lang_key, disabled=True))
                else:
                    choices.append(questionary.Choice(title=label, value=lang_key))

            selected = questionary.checkbox(
                "Select languages to install:",
                choices=choices,
                instruction="(Use SPACE to select, ENTER to confirm)",
            ).ask()

            if selected is None:
                continue

            if not selected:
                console.print(
                    "[yellow]No languages selected. Tip: press SPACE to check a language before pressing ENTER.[/yellow]"
                )
                continue

            for lang_key in selected:
                console.print(
                    f"[bold cyan]Starting installation for {LANGUAGES[lang_key]['display']}...[/bold cyan]"
                )
                install_language(lang_key)

            console.print("[bold green]Done![/bold green]")

        elif choice == "Remove languages":
            installed = get_installed_languages()
            if not installed:
                console.print("[yellow]No languages are currently installed.[/yellow]")
                continue

            choices = [
                questionary.Choice(title=LANGUAGES[k]["display"], value=k)
                for k in installed
            ]
            selected = questionary.checkbox(
                "Select languages to remove:",
                choices=choices,
                instruction="(Use SPACE to select, ENTER to confirm)",
            ).ask()

            if selected is None:
                continue

            if not selected:
                console.print(
                    "[yellow]No languages selected. Tip: press SPACE to check a language before pressing ENTER.[/yellow]"
                )
                continue

            for lang_key in selected:
                uninstall_language(lang_key)

            console.print("[bold green]Done![/bold green]")

        elif choice == "View installed status":
            _status_table()

        elif choice == "Clean Caches (Free Disk Space)":
            bytes_freed, cleaned = clean_caches()
            _print_cache_clean_result(bytes_freed, cleaned)

        elif choice == "Uninstall Everything (Clean Reset)":
            confirmed = questionary.confirm(
                "This will permanently delete all hlowld toolchains, caches, and state. Continue?"
            ).ask()
            if confirmed:
                uninstall_all()
                console.print(
                    "[green]Clean reset complete. ~/.hlowld was completely removed.[/green]"
                )
                break
            console.print("[yellow]Clean reset cancelled.[/yellow]")

        elif choice == "Exit":
            console.print("[green]Goodbye![/green]")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Exiting.[/yellow]")
        sys.exit(0)
