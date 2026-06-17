"""Gateway CLI commands — manage gateway sessions and auth.

Usage:
    python -m cli.main gateway sessions [--platform <platform>]
    python -m cli.main gateway close <platform> <chat_id>
    python -m cli.main gateway allowlist add --platform <p> --id <chat_id>
    python -m cli.main gateway allowlist remove --platform <p> --id <chat_id>
    python -m cli.main gateway auth show
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from weebot.domain.models.gateway_session import GatewaySessionKey

console = Console()
logger = logging.getLogger(__name__)


def _get_session_store():
    """Resolve the gateway session store."""
    from weebot.infrastructure.persistence.gateway_session_store import SQLiteGatewaySessionStore

    from weebot.config.settings import WeebotSettings
    settings = WeebotSettings()
    return SQLiteGatewaySessionStore()


def _get_gateway_auth():
    """Resolve the gateway auth module."""
    from weebot.core.gateway_auth import GatewayAuth
    return GatewayAuth()


@click.group()
def gateway() -> None:
    """Manage gateway sessions and access control."""
    pass


@gateway.group("sessions")
def gateway_sessions() -> None:
    """Manage gateway sessions."""
    pass


@gateway_sessions.command("list")
@click.option("--platform", default=None, help="Filter by platform (telegram, discord, slack)")
@click.option("--all", "show_all", is_flag=True, help="Show all sessions (including inactive)")
def sessions_list(platform: str | None, show_all: bool) -> None:
    """List gateway sessions."""
    store = _get_session_store()

    async def _list():
        sessions = await store.list(
            platform=platform,
            active_only=not show_all,
        )
        return sessions

    sessions = asyncio.run(_list())

    if not sessions:
        console.print("[yellow]No gateway sessions found.[/yellow]")
        return

    table = Table(title=f"Gateway Sessions ({'all' if show_all else 'active'})")
    table.add_column("Platform", style="cyan")
    table.add_column("Chat ID", style="magenta")
    table.add_column("Chat Type", style="blue")
    table.add_column("Flow Session", style="green")
    table.add_column("Last Activity", style="white")
    table.add_column("Status", style="yellow")

    for s in sessions:
        status = "🟢 Active" if s.is_active else "🔴 Inactive"
        table.add_row(
            s.key.platform,
            s.key.chat_id,
            s.key.chat_type,
            s.flow_session_id[:20],
            s.last_activity_at.strftime("%Y-%m-%d %H:%M"),
            status,
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(sessions)} session(s)[/dim]")


@gateway_sessions.command("close")
@click.argument("platform")
@click.argument("chat_id")
def sessions_close(platform: str, chat_id: str) -> None:
    """Close a gateway session by platform and chat ID."""
    store = _get_session_store()
    key = GatewaySessionKey(platform=platform, chat_type="private", chat_id=chat_id)

    async def _close():
        await store.close_session(key)

    asyncio.run(_close())
    console.print(f"[green]Closed session: {platform}:{chat_id}[/green]")


@gateway.group("allowlist")
def gateway_allowlist() -> None:
    """Manage gateway allowlist entries."""
    pass


@gateway_allowlist.command("add")
@click.option("--platform", required=True, help="Platform (telegram, discord, slack)")
@click.option("--id", "entity_id", required=True, help="Chat or user ID to allow")
@click.option("--type", "entity_type", type=click.Choice(["chat", "user"]),
              default="chat", help="Entity type")
def allowlist_add(platform: str, entity_id: str, entity_type: str) -> None:
    """Add a chat or user to the allowlist."""
    auth = _get_gateway_auth()
    if entity_type == "chat":
        auth.allow_chat(platform, entity_id)
        console.print(f"[green]Added chat {entity_id} to {platform} allowlist[/green]")
    else:
        auth.allow_user(platform, entity_id)
        console.print(f"[green]Added user {entity_id} to {platform} allowlist[/green]")


@gateway_allowlist.command("remove")
@click.option("--platform", required=True, help="Platform (telegram, discord, slack)")
@click.option("--id", "entity_id", required=True, help="Chat or user ID to block")
@click.option("--type", "entity_type", type=click.Choice(["chat", "user"]),
              default="chat", help="Entity type")
def allowlist_remove(platform: str, entity_id: str, entity_type: str) -> None:
    """Block a chat or user."""
    auth = _get_gateway_auth()
    if entity_type == "chat":
        auth.block_chat(platform, entity_id)
        console.print(f"[yellow]Blocked chat {entity_id} on {platform}[/yellow]")
    else:
        auth.block_user(platform, entity_id)
        console.print(f"[yellow]Blocked user {entity_id} on {platform}[/yellow]")


@gateway_allowlist.command("list")
def allowlist_list() -> None:
    """Show all allowlist entries."""
    auth = _get_gateway_auth()
    config = auth.get_config()

    table = Table(title="Gateway Auth Config")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Allowed Platforms", ", ".join(config.get("allowed_platforms", [])))
    table.add_row("Allow All By Default", str(config.get("allow_all_by_default", False)))

    allowed_chats = config.get("allowed_chats", {})
    for platform, chats in allowed_chats.items():
        table.add_row(f"Allowed Chats ({platform})", ", ".join(chats) if chats else "(none)")

    allowed_users = config.get("allowed_users", {})
    for platform, users in allowed_users.items():
        table.add_row(f"Allowed Users ({platform})", ", ".join(users) if users else "(none)")

    blocked = config.get("blocked_users", {})
    for platform, users in blocked.items():
        table.add_row(f"Blocked ({platform})", ", ".join(users) if users else "(none)")

    console.print(table)


@gateway.command("auth")
@click.option("--platform", default=None, help="Platform to show auth for")
def gateway_auth(platform: str | None) -> None:
    """Show gateway auth configuration."""
    auth = _get_gateway_auth()
    config = auth.get_config()

    if platform:
        allowed = platform in config.get("allowed_platforms", [])
        console.print(f"[bold]{platform}[/bold] allowed: {'✅' if allowed else '❌'}")
    else:
        console.print(f"Platforms: {', '.join(config.get('allowed_platforms', []))}")
        console.print(f"Allow all by default: {config.get('allow_all_by_default', False)}")
        console.print(f"Blocked users: {sum(len(v) for v in config.get('blocked_users', {}).values())}")


if __name__ == "__main__":
    gateway()
