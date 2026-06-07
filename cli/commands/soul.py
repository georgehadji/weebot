"""Soul CLI — manage SOUL.md agent identity files.

Usage:
    python -m cli.main soul show
    python -m cli.main soul show --profile coder
    python -m cli.main soul edit
    python -m cli.main soul seed --profile reviewer
    python -m cli.main soul list
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()


@click.group()
def soul() -> None:
    """Manage SOUL.md agent identity files."""
    pass


@soul.command("show")
@click.option("--profile", "-p", default=None, help="Profile name (e.g. 'coder', 'reviewer').")
def soul_show(profile: str | None) -> None:
    """Display the current SOUL.md content."""
    async def _run():
        provider = _get_provider()
        soul_profile = await provider.load(profile)
        name = profile or "default"

        if soul_profile is None or soul_profile.is_empty:
            console.print(f"[yellow]No SOUL.md found for profile '{name}'.[/yellow]")
            console.print("[dim]Run 'weebot soul seed' to create one.[/dim]")
            return

        source = soul_profile.source_path or "unknown"
        console.print(
            Panel(
                Syntax(soul_profile.content, "markdown", theme="monokai", line_numbers=False),
                title=f"SOUL.md — {name}",
                subtitle=source,
            )
        )

    asyncio.run(_run())


@soul.command("edit")
@click.option("--profile", "-p", default=None, help="Profile name to edit.")
def soul_edit(profile: str | None) -> None:
    """Open SOUL.md in your default editor ($EDITOR or notepad)."""
    async def _run():
        provider = _get_provider()
        name = profile or "default"

        # Determine file path
        if profile:
            profiles_dir = Path.home() / ".weebot" / "profiles" / profile
            path = profiles_dir / "SOUL.md"
        else:
            path = Path.cwd() / "SOUL.md"

        # Ensure it exists (auto-seed)
        soul_profile = await provider.load(profile)
        if soul_profile is None:
            console.print("[yellow]SOUL.md not found — seeding template first...[/yellow]")
            soul_profile = await provider.seed(profile)
            console.print(f"[green]Created {soul_profile.source_path}[/green]")

        # Open in editor
        editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
        if not editor:
            # Windows fallback
            if os.name == "nt":
                editor = "notepad"
            else:
                editor = "nano"

        console.print(f"[dim]Opening {path} with {editor}...[/dim]")
        subprocess.run([editor, str(path)], check=False)
        console.print(f"[green]Done. Run 'weebot soul show{' --profile ' + profile if profile else ''}' to review.[/green]")

    asyncio.run(_run())


@soul.command("seed")
@click.option("--profile", "-p", default=None, help="Profile name to seed.")
def soul_seed(profile: str | None) -> None:
    """Create a SOUL.md file from the default template."""
    async def _run():
        provider = _get_provider()
        name = profile or "default"

        try:
            soul_profile = await provider.seed(profile)
            console.print(f"[green]Created SOUL.md for '{name}' at {soul_profile.source_path}[/green]")
        except FileExistsError:
            console.print(f"[yellow]SOUL.md already exists for '{name}'. Use 'soul edit' to modify it.[/yellow]")

    asyncio.run(_run())


@soul.command("list")
def soul_list() -> None:
    """List all profiles with SOUL.md files."""
    async def _run():
        provider = _get_provider()
        profiles = await provider.list_profiles()

        if not profiles:
            console.print("[dim]No SOUL.md profiles found.[/dim]")
            console.print("[dim]Run 'weebot soul seed' to create one.[/dim]")
            return

        table = Table(title="SOUL.md Profiles")
        table.add_column("Profile", style="cyan")
        table.add_column("Status", style="green")

        for p in profiles:
            soul_profile = await provider.load(p if p != "default" else None)
            chars = soul_profile.char_count if soul_profile else 0
            status = f"{chars} chars" if chars > 0 else "empty"
            table.add_row(p, status)

        console.print(table)

    asyncio.run(_run())


# ── Helpers ──────────────────────────────────────────────────────────

def _get_provider():
    """Resolve SoulProviderPort from the DI container."""
    from weebot.application.di import Container
    c = Container()
    c.configure_defaults()
    return c.get("soul_provider")
