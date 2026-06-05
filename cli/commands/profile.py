"""CLI commands — profile"""
from __future__ import annotations
from pathlib import Path

import click
from rich.console import Console

console = Console()

@click.group()
def profile() -> None:
    """Manage named profiles with isolated configuration."""
    pass


@profile.command("create")
@click.argument("name")
@click.option("--from-profile", default=None, help="Copy settings from an existing profile")
def profile_create(name: str, from_profile: str | None) -> None:
    """Create a new profile with isolated config."""
    from weebot.application.services.profile_manager import ProfileManager

    mgr = ProfileManager()
    try:
        p = mgr.create(name, from_profile=from_profile)
        console.print(f"[green]✓[/green] Created profile '[cyan]{p.name}[/cyan]' at {p.path}")
    except ValueError as exc:
        console.print(f"[red]✗[/red] {exc}")


@profile.command("list")
def profile_list() -> None:
    """List all available profiles."""
    from weebot.application.services.profile_manager import ProfileManager
    from rich.table import Table

    mgr = ProfileManager()
    profiles = mgr.list_profiles()

    if not profiles:
        console.print("[dim]No profiles found. Run 'weebot profile create <name>' to create one.[/dim]")
        return

    active = ProfileManager.active_profile_name()
    table = Table(title="Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Active", style="green")

    for p in profiles:
        is_active = "✓" if p.name == active else ""
        table.add_row(p.name, str(p.path), is_active)
    console.print(table)


@profile.command("switch")
@click.argument("name")
def profile_switch(name: str) -> None:
    """Switch to an existing profile."""
    from weebot.application.services.profile_manager import ProfileManager

    mgr = ProfileManager()
    profile = mgr.switch(name)
    if profile is None:
        console.print(f"[red]✗[/red] Profile '{name}' not found.")
        return
    console.print(f"[green]✓[/green] Switched to profile '[cyan]{profile.name}[/cyan]'")


@profile.command("delete")
@click.argument("name")
@click.confirmation_option(prompt=f"Delete profile '{{name}}'?")
def profile_delete(name: str) -> None:
    """Delete a profile and its directory."""
    from weebot.application.services.profile_manager import ProfileManager

    mgr = ProfileManager()
    try:
        if mgr.delete(name):
            console.print(f"[green]✓[/green] Deleted profile '[cyan]{name}[/cyan]'")
        else:
            console.print(f"[yellow]Profile '{name}' not found.[/yellow]")
    except ValueError as exc:
        console.print(f"[red]✗[/red] {exc}")

