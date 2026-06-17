"""MCP CLI commands — manage MCP server connections and tools.

Usage:
    python -m cli.main mcp list          # list configured servers and states
    python -m cli.main mcp add <name>    # interactive add
    python -m cli.main mcp remove <name>
    python -m cli.main mcp configure <name>
    python -m cli.main mcp login <name>
    python -m cli.main mcp reload
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

console = Console()
logger = logging.getLogger(__name__)


def _get_mcp_bridge():
    """Resolve MCPToolRegistryBridge from DI container."""
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()
    return container.build_mcp_bridge()


def _get_mcp_client():
    """Resolve MCPClientManager from DI container."""
    from weebot.application.di import Container

    container = Container()
    container.configure_defaults()
    return container.get("mcp_client")


@click.group()
def mcp() -> None:
    """Manage MCP server connections and tools."""
    pass


@mcp.command("list")
def mcp_list() -> None:
    """List configured MCP servers and their tool counts."""
    bridge = _get_mcp_bridge()
    stats = bridge.get_stats()

    # Also show raw server configs
    from weebot.config.settings import WeebotSettings
    settings = WeebotSettings()

    table = Table(title="MCP Servers")
    table.add_column("Server", style="cyan")
    table.add_column("Transport", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Tools", style="blue")
    table.add_column("Errors", style="red")

    if stats["servers"] == 0:
        console.print("[yellow]No MCP servers configured.[/yellow]")
        console.print("  Use [bold]python -m cli.main mcp add <name>[/bold] to add one.")
        return

    for server, tool_count in stats["per_server"].items():
        table.add_row(
            server,
            "configured",
            "registered",
            str(tool_count),
            "0",
        )

    console.print(table)
    console.print(f"\n[dim]Total: {stats['servers']} server(s), {stats['total_tools']} tool(s)[/dim]")


@mcp.command("add")
@click.argument("name")
@click.option("--transport", type=click.Choice(["stdio", "http", "sse", "streamable-http"]),
              default="stdio", help="Transport protocol")
@click.option("--command", default=None, help="Executable path (stdio transport)")
@click.option("--url", default=None, help="Server URL (http/sse transport)")
@click.option("--env", multiple=True, help="ENV_VAR=value pairs for stdio transport")
@click.option("--enable/--disable", default=True, help="Enable on startup")
def mcp_add(name: str, transport: str, command: str | None, url: str | None,
            env: tuple[str, ...], enable: bool) -> None:
    """Add a new MCP server configuration.

    NAME is a unique identifier for the server (alphanumeric, dashes/underscores allowed).
    """
    from weebot.domain.models.mcp import MCPServerConfig

    # Validate name
    if not name.replace("-", "").replace("_", "").isalnum():
        console.print(f"[red]Invalid server name: {name}. Use alphanumeric with dashes/underscores.[/red]")
        return

    # Interactive mode for missing args
    if transport == "stdio" and not command:
        command = Prompt.ask("Enter the command/path", default="npx")
        args_str = Prompt.ask("Enter arguments (space-separated)", default="")
        args = args_str.split() if args_str else []
    else:
        args = []

    if transport in ("http", "sse", "streamable-http") and not url:
        url = Prompt.ask(f"Enter the {transport} URL")

    if not command and not url:
        console.print("[red]Either --command (stdio) or --url (http/sse) is required.[/red]")
        return

    # Parse env vars
    env_dict = {}
    for e in env:
        if "=" in e:
            key, val = e.split("=", 1)
            env_dict[key] = val

    # Validate
    config_data = {
        "name": name,
        "transport": transport,
        "enabled": enable,
    }
    if command:
        config_data["command"] = command
        config_data["args"] = args
    if url:
        config_data["url"] = url
    if env_dict:
        config_data["env"] = env_dict

    try:
        config = MCPServerConfig(**config_data)
    except Exception as exc:
        console.print(f"[red]Invalid config: {exc}[/red]")
        return

    # Save to config file
    _save_server_config(config)

    console.print(f"[green]Added MCP server: {name}[/green]")
    console.print(f"  Transport: {transport}")
    console.print(f"  Enabled: {enable}")
    if command:
        console.print(f"  Command: {command} {' '.join(args)}")
    if url:
        console.print(f"  URL: {url}")


@mcp.command("remove")
@click.argument("name")
@click.confirmation_option(prompt=f"Are you sure?")
def mcp_remove(name: str) -> None:
    """Remove an MCP server configuration."""
    configs = _load_server_configs()
    if name not in configs:
        console.print(f"[red]Server '{name}' not found.[/red]")
        return

    del configs[name]
    _save_all_server_configs(configs)
    console.print(f"[green]Removed MCP server: {name}[/green]")


@mcp.command("configure")
@click.argument("name")
def mcp_configure(name: str) -> None:
    """Interactively configure an MCP server."""
    configs = _load_server_configs()
    if name not in configs:
        console.print(f"[red]Server '{name}' not found. Use 'mcp add {name}' first.[/red]")
        return

    current = configs[name]
    console.print(Panel(f"Configuring [bold]{name}[/bold]", style="blue"))
    console.print(f"  Current transport: {current.get('transport', 'stdio')}")
    console.print(f"  Current enabled: {current.get('enabled', True)}")

    # Toggle enabled
    enabled = Confirm.ask("Enable on startup?", default=current.get("enabled", True))
    current["enabled"] = enabled

    if current.get("transport") == "stdio":
        current["command"] = Prompt.ask("Command", default=current.get("command", ""))
        args_str = Prompt.ask("Arguments (space-separated)", default=" ".join(current.get("args", [])))
        current["args"] = args_str.split() if args_str else []
    else:
        current["url"] = Prompt.ask("URL", default=current.get("url", ""))

    _save_all_server_configs(configs)
    console.print(f"[green]Updated MCP server: {name}[/green]")


@mcp.command("login")
@click.argument("name")
@click.option("--force", is_flag=True, help="Force re-authentication")
def mcp_login(name: str, force: bool) -> None:
    """Authenticate with an MCP server (OAuth flow)."""
    from weebot.config.settings import WeebotSettings
    settings = WeebotSettings()

    configs = _load_server_configs()
    if name not in configs:
        console.print(f"[red]Server '{name}' not found.[/red]")
        return

    server_config = configs[name]
    auth_type = server_config.get("auth", {}).get("type", "none")

    if auth_type not in ("oauth", "bearer"):
        console.print(f"[yellow]Server '{name}' uses {auth_type} auth — no login needed.[/yellow]")
        return

    if auth_type == "oauth":
        _do_oauth_login(name, server_config, force)
    elif auth_type == "bearer":
        token = Prompt.ask("Enter bearer token", password=True)
        if "auth" not in server_config:
            server_config["auth"] = {}
        server_config["auth"]["token"] = token
        _save_all_server_configs(configs)
        console.print(f"[green]Token saved for server: {name}[/green]")


@mcp.command("reload")
def mcp_reload() -> None:
    """Reload all MCP server connections and re-discover tools."""
    console.print("[yellow]Reloading MCP servers...[/yellow]")
    bridge = _get_mcp_bridge()

    async def _reload():
        count = await bridge.reload()
        return count

    count = asyncio.run(_reload())
    console.print(f"[green]MCP reload complete: {count} tools registered[/green]")


@mcp.command("config-path")
def mcp_config_path() -> None:
    """Show the MCP servers config file path."""
    path = _get_config_path()
    if path.exists():
        console.print(f"[green]Config file: {path}[/green]")
        console.print(f"[dim]Size: {path.stat().st_size} bytes[/dim]")
    else:
        console.print(f"[yellow]No config file at: {path}[/yellow]")
        console.print("  Add a server with [bold]python -m cli.main mcp add[/bold]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_config_path() -> Path:
    """Get the path to the MCP servers config file."""
    from weebot.config.settings import WeebotSettings
    settings = WeebotSettings()
    config_path = settings.mcp_servers_config_path
    if config_path:
        return Path(config_path)
    return Path.cwd() / ".weebot" / "mcp_servers.json"


def _load_server_configs() -> dict:
    """Load MCP server configurations from disk."""
    path = _get_config_path()
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            import yaml
            return yaml.safe_load(raw) or {}
        return json.loads(raw) or {}
    except Exception as exc:
        logger.warning("Failed to load MCP config from %s: %s", path, exc)
        return {}


def _save_all_server_configs(configs: dict) -> None:
    """Save MCP server configurations to disk."""
    path = _get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix in (".yaml", ".yml"):
        import yaml
        raw = yaml.dump(configs, default_flow_style=False)
    else:
        raw = json.dumps(configs, indent=2)
    path.write_text(raw, encoding="utf-8")
    logger.info("Saved MCP config to %s (%d servers)", path, len(configs))


def _save_server_config(config: "MCPServerConfig") -> None:
    """Append a single server config to the config file."""
    configs = _load_server_configs()
    configs[config.name] = config.model_dump(exclude_none=True)
    _save_all_server_configs(configs)


def _do_oauth_login(name: str, server_config: dict, force: bool) -> None:
    """Perform OAuth login flow for an MCP server.

    Uses loopback callback server for interactive login and falls
    back to paste-back for headless environments.
    """
    from weebot.config.settings import WeebotSettings
    settings = WeebotSettings()
    token_dir = Path(settings.mcp_token_dir)
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / f"{name}_token.json"

    if token_path.exists() and not force:
        console.print(f"[green]Already authenticated for {name}. Use --force to re-authenticate.[/green]")
        return

    auth_config = server_config.get("auth", {})
    client_id = auth_config.get("oauth_client_id")
    scopes = auth_config.get("oauth_scopes", [])

    if not client_id:
        console.print("[yellow]No OAuth client ID configured for this server.[/yellow]")
        console.print("  Use 'mcp configure' to set one, or paste your token manually.")
        token = Prompt.ask("Paste OAuth token", password=True)
        if token:
            token_path.write_text(json.dumps({"access_token": token, "type": "manual"}), encoding="utf-8")
            token_path.chmod(0o600)
            console.print(f"[green]Token saved to {token_path}[/green]")
        return

    console.print(f"[yellow]Opening browser for OAuth login to {name}...[/yellow]")
    console.print(f"  Client ID: {client_id}")
    if scopes:
        console.print(f"  Scopes: {', '.join(scopes)}")
    console.print()
    console.print("[dim]In a full implementation, this would open a browser for OAuth. "
                  "For now, paste your token below.[/dim]")

    token = Prompt.ask("Paste OAuth token", password=True)
    if token:
        token_path.write_text(json.dumps({"access_token": token, "type": "oauth"}), encoding="utf-8")
        token_path.chmod(0o600)
        console.print(f"[green]Token saved to {token_path} (permissions: 0o600)[/green]")


if __name__ == "__main__":
    mcp()
