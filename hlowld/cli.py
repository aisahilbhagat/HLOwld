"""Interactive CLI entry point for hlowld."""

import subprocess
import sys
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hlowld.config import LANGUAGES, check_os
from hlowld.installer import get_installed_languages, install_language, uninstall_language

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

    result = subprocess.run([str(engine_bin), *args])
    sys.exit(result.returncode)


def main() -> None:
    check_os()

    cli_args = sys.argv[1:]
    if cli_args:
        _run_engine(cli_args)

    _header()

    while True:
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                "Install languages",
                "Remove languages",
                "View installed status",
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

        elif choice == "Exit":
            console.print("[green]Goodbye![/green]")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Exiting.[/yellow]")
        sys.exit(0)
