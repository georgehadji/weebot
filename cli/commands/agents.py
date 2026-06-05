"""Agent CLI commands — manage personas and packs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def agents() -> None:
    """Manage agent personas and packs."""
    pass


@agents.command("import")
@click.argument("path", type=click.Path(exists=True))
def agents_import(path: str) -> None:
    """Import agent personas from a file, directory, or zip bundle."""
    from weebot.agents.registry import AgentRegistry
    registry = AgentRegistry(Path.cwd())
    personas = registry.import_path(Path(path))
    console.print(f"[green]Imported {len(personas)} persona(s)[/green]")


@agents.command("export")
@click.argument("bundle", type=click.Path())
@click.option("--ids", default="", help="Comma-separated persona IDs to export")
def agents_export(bundle: str, ids: str) -> None:
    """Export personas into a zip bundle."""
    from weebot.agents.registry import AgentRegistry
    registry = AgentRegistry(Path.cwd())
    persona_ids = [i.strip() for i in ids.split(",") if i.strip()]
    output_path = registry.export_bundle(Path(bundle), persona_ids=persona_ids or None)
    console.print(f"[green]Exported bundle: {output_path}[/green]")


@agents.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def agents_list(json_output: bool) -> None:
    """List registered agent personas."""
    from weebot.agents.registry import AgentRegistry
    registry = AgentRegistry(Path.cwd())
    personas = registry.list_personas()
    if not personas:
        console.print("[yellow]No personas registered[/yellow]"); return
    if json_output:
        console.print_json(json.dumps([p.as_dict() for p in personas])); return
    table = Table(title="Agent Personas")
    table.add_column("ID", style="cyan"); table.add_column("Name", style="magenta")
    table.add_column("Division", style="green"); table.add_column("Role", style="yellow")
    for p in personas:
        table.add_row(p.persona_id, p.name, p.division or "-", p.role)
    console.print(table)


@agents.command("describe")
@click.argument("persona_id")
def agents_describe(persona_id: str) -> None:
    """Show details for a persona."""
    from weebot.agents.registry import AgentRegistry
    registry = AgentRegistry(Path.cwd())
    persona = registry.get(persona_id)
    if not persona:
        console.print(f"[red]Persona not found: {persona_id}[/red]"); return
    console.print_json(json.dumps(persona.as_dict()))


@agents.command("route")
@click.argument("task", nargs=-1)
def agents_route(task: tuple[str, ...]) -> None:
    """Route a task to the best persona."""
    from weebot.agents.registry import AgentRegistry
    from weebot.agents.router import PersonaRouter
    task_text = " ".join(task).strip()
    if not task_text:
        console.print("[red]Task description required[/red]"); return
    registry = AgentRegistry(Path.cwd()); personas = registry.list_personas()
    if not personas:
        console.print("[yellow]No personas registered[/yellow]"); return
    scored = PersonaRouter().route(personas, task_text, top_n=3)
    table = Table(title="Persona Routing")
    table.add_column("Rank", style="cyan"); table.add_column("Persona", style="magenta"); table.add_column("Score", style="green")
    for i, item in enumerate(scored, start=1):
        table.add_row(str(i), item.persona.name, f"{item.score:.2f}")
    console.print(table)


@agents.command("validate-output")
@click.argument("persona_id")
@click.argument("output_file", type=click.Path(exists=True))
def agents_validate_output(persona_id: str, output_file: str) -> None:
    """Validate output against a persona's deliverable template."""
    from weebot.agents.registry import AgentRegistry
    registry = AgentRegistry(Path.cwd()); persona = registry.get(persona_id)
    if not persona:
        console.print(f"[red]Persona not found: {persona_id}[/red]"); return
    output = Path(output_file).read_text(encoding="utf-8")
    missing = persona.validate_output(output)
    if not missing:
        console.print("[green]Output satisfies deliverable contract[/green]")
    else:
        console.print("[yellow]Missing sections:[/yellow]")
        for item in missing:
            console.print(f"- {item}")


@agents.command("sync-claude")
@click.option("--target", default=str(Path.home() / ".claude" / "agents"))
@click.option("--force", is_flag=True, help="Overwrite existing files")
def agents_sync_claude(target: str, force: bool) -> None:
    """Sync personas to Claude Code agents directory."""
    from weebot.agents.registry import AgentRegistry
    registry = AgentRegistry(Path.cwd())
    synced = registry.sync_to_claude(Path(target), force=force)
    console.print(f"[green]Synced {len(synced)} file(s) to {target}[/green]")


@agents.group("pack")
def agents_pack() -> None:
    """Manage agent packs (division-based)."""
    pass


@agents_pack.command("list")
def agents_pack_list() -> None:
    """List available divisions."""
    from weebot.agents.registry import AgentRegistry
    divisions = AgentRegistry(Path.cwd()).list_divisions()
    if not divisions:
        console.print("[yellow]No divisions found[/yellow]"); return
    for d in divisions:
        console.print(f"- {d}")


@agents_pack.command("apply")
@click.argument("division")
@click.option("--execute", is_flag=True, help="Spawn agents now")
def agents_pack_apply(division: str, execute: bool) -> None:
    """Create or spawn a division pack."""
    from weebot.agents.registry import AgentRegistry
    from weebot.core.agent_context import AgentContext
    from weebot.core.agent_factory import AgentFactory
    from weebot.tools.tool_registry import RoleBasedToolRegistry
    registry = AgentRegistry(Path.cwd()); personas = registry.pack(division)
    if not personas:
        console.print(f"[red]No personas for division: {division}[/red]"); return
    tool_registry = RoleBasedToolRegistry()
    seen_roles = {}; specs = []
    for persona in personas:
        base_role = persona.role or persona.name
        count = seen_roles.get(base_role, 0) + 1; seen_roles[base_role] = count
        role = base_role if count == 1 else f"{base_role}_{count}"
        try:
            tools = persona.tools or tool_registry.get_tools_for_role(base_role)
        except ValueError:
            tools = tool_registry.get_tools_for_role("custom")
        specs.append({"role": role, "description": persona.mission or persona.description or persona.name,
                      "tools": tools, "config_overrides": {"daily_budget": 10.0}})
    if not execute:
        console.print("[yellow]Dry run — use --execute to spawn agents[/yellow]")
        console.print_json(json.dumps(specs)); return
    async def _spawn():
        ctx = AgentContext.create_orchestrator()
        await AgentFactory().spawn_orchestrator_agents(ctx, ctx.agent_id, specs)
    asyncio.run(_spawn())
    console.print(f"[green]Spawned {len(specs)} agent(s) for division {division}[/green]")
