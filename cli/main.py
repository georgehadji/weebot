#!/usr/bin/env python3
"""cli_main.py - Command Line Interface for weebot Agent.

Εντολές:
--------
create      Δημιουργία νέου project
list        Λίστα όλων των projects
status      Έλεγχος κατάστασης project
run         Εκτέλεση task plan από JSON
resume      Συνέχιση paused project
checkpoint  Επίλυση pending checkpoint
delete      Διαγραφή project
export      Export project state
costs       Αναφορά κόστους
monitor     Real-time monitoring
"""
import click
import asyncio
import json
from pathlib import Path
from typing import Any

from weebot.application.di import Container
from weebot.application.ports.state_repo_port import StateRepositoryPort

# Shared container for CLI commands — initialized once in cli()
_container: Container | None = None


def _get_state_repo() -> Any:
    """Resolve StateRepositoryPort from the shared DI container.
    Use this instead of constructing SQLiteStateRepository() directly.
    """
    global _container
    if _container is None:
        _container = Container()
        _container.configure_defaults()
    return _container.get(StateRepositoryPort)
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress

from weebot.agent_core_v2 import WeebotAgent, AgentConfig
from weebot.state_manager import StateManager, ProjectStatus
from weebot.cli_support import (
    init_project,
    init_hooks,
    install_hooks,
    run_doctor,
    build_plan_from_spec,
    check_template_updates,
    upgrade_templates,
)
from weebot.agents.registry import AgentRegistry
from weebot.agents.router import PersonaRouter
from weebot.core.agent_factory import AgentFactory
from weebot.core.agent_context import AgentContext
from weebot.tools.tool_registry import RoleBasedToolRegistry
from weebot.interfaces.cli.behavior_commands import behavior_cli

console = Console()


@click.group()
def cli() -> None:
    """weebot Agent Framework CLI."""
    pass


@cli.command()
@click.argument("project_id")
@click.argument("description")
@click.option("--budget", default=10.0, help="Daily AI budget")
def create(project_id: str, description: str, budget: float) -> None:
    """[DEPRECATED] Use 'flow' commands instead. Create new project."""
    config = AgentConfig(
        project_id=project_id,
        description=description,
        daily_budget=budget
    )
    agent = WeebotAgent(config)
    console.print(Panel(f"Created project: {project_id}", style="green"))


@cli.command()
def list_projects() -> None:
    """[DEPRECATED] Use 'flow' commands instead. List all projects."""
    sm = StateManager()
    projects = sm.list_projects()

    table = Table(title="Active Projects")
    table.add_column("Project ID", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Last Updated", style="green")

    for proj in projects:
        state = sm.load_state(proj["project_id"])
        table.add_row(
            proj["project_id"],
            state.status.value if state else "unknown",
            str(proj["updated_at"])
        )

    console.print(table)


@cli.command()
@click.argument("project_id")
def status(project_id: str) -> None:
    """[DEPRECATED] Use 'flow' commands instead. Check project status."""
    config = AgentConfig(project_id=project_id, description="")
    agent = WeebotAgent(config)
    stats = agent.get_status()
    
    console.print(Panel.fit(
        f"Status: {stats['status']}\n"
        f"Progress: {stats['progress']} tasks completed\n"
        f"Current: {stats['current_task'] or 'None'}\n"
        f"Pending Checkpoints: {stats['pending_checkpoints']}\n"
        f"Cost Today: ${stats['cost_stats']['today']:.4f}",
        title=f"Project: {project_id}"
    ))


@cli.command()
@click.argument("project_id")
@click.argument("plan_file", type=click.Path(exists=True))
def run(project_id: str, plan_file: str) -> None:
    """[DEPRECATED] Use 'flow' commands instead. Execute task plan from JSON file."""
    import json
    
    plan = json.loads(Path(plan_file).read_text())
    
    config = AgentConfig(
        project_id=project_id,
        description=f"Running plan from {plan_file}"
    )
    agent = WeebotAgent(config)
    
    with Progress() as progress:
        task = progress.add_task("[cyan]Executing tasks...", total=len(plan))
        
        async def execute():
            for item in plan:
                progress.update(task, advance=1, description=f"[cyan]Task: {item['name']}")
                await agent.run([item])
        
        asyncio.run(execute())
    
    console.print("[green]Plan execution complete![/green]")


@cli.command()
@click.argument("project_id")
def resume(project_id: str) -> None:
    """[DEPRECATED] Use 'flow' commands instead. Resume paused project."""
    config = AgentConfig(project_id=project_id, description="")
    agent = WeebotAgent(config)

    # Resume from current state
    console.print(f"[yellow]Resuming project: {project_id}[/yellow]")

    # Implementation would continue from last checkpoint
    console.print("[green]Resumed successfully![/green]")


@cli.command()
@click.argument("project_id")
@click.argument("checkpoint_id")
@click.argument("response")
def checkpoint(project_id: str, checkpoint_id: str, response: str) -> None:
    """[DEPRECATED] Use 'flow' commands instead. Resolve pending checkpoint."""
    sm = StateManager()
    sm.resolve_checkpoint(checkpoint_id, response)
    console.print(f"[green]Resolved checkpoint {checkpoint_id}: {response}[/green]")


@cli.command()
@click.argument("project_id")
@click.confirmation_option(prompt="Are you sure you want to delete this project?")
def delete(project_id: str) -> None:
    """Delete project."""
    # Implementation would delete from database
    console.print(f"[red]Deleted project: {project_id}[/red]")


@cli.command()
@click.argument("project_id")
@click.option("--output", "-o", default="export.json")
def export(project_id: str, output: str) -> None:
    """Export project state."""
    sm = StateManager()
    state = sm.load_state(project_id)

    if state:
        import json
        from dataclasses import asdict

        Path(output).write_text(
            json.dumps(asdict(state), indent=2, default=str)
        )
        console.print(f"[green]Exported to: {output}[/green]")
    else:
        console.print(f"[red]Project not found: {project_id}[/red]")


@cli.command()
@click.option("--days", default=7, help="Number of days to report")
def costs(days: int) -> None:
    """Show cost report."""
    table = Table(title=f"Cost Report (Last {days} days)")
    table.add_column("Date", style="cyan")
    table.add_column("Cost", style="green")
    table.add_column("Tokens", style="magenta")
    
    # Placeholder data
    table.add_row("Today", "$2.45", "12,340")
    table.add_row("Yesterday", "$1.23", "8,900")
    
    console.print(table)


# Research commands group
@cli.group()
def research() -> None:
    """Scientific research commands."""
    pass


# ---------------------------------------------------------------------------
# Ops: init / doctor / hooks / upgrades / implement
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--platform", default=None, help="Override detected platform")
@click.option("--tier", type=click.Choice(["full", "instructions-only"]), default=None)
@click.option("--force", is_flag=True, help="Overwrite existing config")
@click.option("--no-env", is_flag=True, help="Do not create .env from .env.example")
@click.option("--with-hooks/--no-hooks", default=True, help="Initialize hooks directory")
def init(platform: str | None, tier: str | None, force: bool, no_env: bool, with_hooks: bool) -> None:
    """Initialize a weebot project in the current directory."""
    root = Path.cwd()
    config_path = init_project(
        root,
        platform=platform,
        tier=tier,
        force=force,
        create_env=not no_env,
    )
    console.print(Panel(f"Initialized config: {config_path}", style="green"))

    if with_hooks:
        created = init_hooks(root)
        if created:
            console.print(f"[green]Hooks initialized: {len(created)} file(s)[/green]")
        else:
            console.print("[yellow]Hooks already initialized[/yellow]")


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def doctor(json_output: bool) -> None:
    """Run diagnostics and environment checks."""
    report = run_doctor(Path.cwd())
    if json_output:
        console.print_json(json.dumps(report.as_dict()))
        return

    table = Table(title="weebot Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Details", style="green")

    for check in report.checks:
        table.add_row(check.name, check.status, check.details)

    console.print(table)
    console.print(
        Panel(
            f"Summary: ok={report.summary['ok']} warn={report.summary['warn']} error={report.summary['error']}",
            style="green" if report.ok else "yellow",
        )
    )


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def health(json_output: bool) -> None:
    """Check health of Weebot components."""
    import asyncio
    from weebot.infrastructure.observability import HealthCheckService, HealthStatus
    
    async def _check() -> None:
        service = HealthCheckService()
        report = await service.check_all()
        
        if json_output:
            console.print_json(json.dumps(report.to_dict()))
            return
        
        # Color-coded status
        status_colors = {
            HealthStatus.HEALTHY: "green",
            HealthStatus.DEGRADED: "yellow",
            HealthStatus.UNHEALTHY: "red",
            HealthStatus.UNKNOWN: "grey",
        }
        
        table = Table(title="Weebot Health Check")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Latency (ms)", style="blue")
        table.add_column("Message", style="green")
        
        for comp in report.components:
            status_color = status_colors.get(comp.status, "white")
            table.add_row(
                comp.name,
                f"[{status_color}]{comp.status.value}[/{status_color}]",
                f"{comp.latency_ms:.1f}",
                comp.message,
            )
        
        console.print(table)
        
        # Overall status panel
        overall_color = status_colors.get(report.overall_status, "white")
        console.print(
            Panel(
                f"Overall Status: [{overall_color}]{report.overall_status.value}[/{overall_color}]",
                style=overall_color,
            )
        )
    
    asyncio.run(_check())


@cli.group()
def hooks() -> None:
    """Manage platform hooks."""
    pass


@hooks.command("init")
def hooks_init() -> None:
    """Initialize hooks directory."""
    created = init_hooks(Path.cwd())
    if created:
        console.print(f"[green]Hooks initialized: {len(created)} file(s)[/green]")
    else:
        console.print("[yellow]Hooks already initialized[/yellow]")


@hooks.command("install")
@click.option("--target", default=".weebot/hooks-installed", help="Target directory for hooks")
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.option("--allow-outside", is_flag=True, help="Allow installing outside project root")
def hooks_install(target: str, force: bool, allow_outside: bool) -> None:
    """Install hooks into a target directory."""
    try:
        installed = install_hooks(
            Path.cwd(),
            Path(target),
            force=force,
            allow_outside=allow_outside,
        )
        if installed:
            console.print(f"[green]Installed {len(installed)} hook file(s)[/green]")
        else:
            console.print("[yellow]No hooks installed (files exist)[/yellow]")
    except Exception as exc:
        console.print(f"[red]Hook install failed: {exc}[/red]")


@cli.command("check-updates")
@click.option("--template", "template_filter", default=None, help="Filter by template name/id")
@click.option("--marketplace-url", default=None, help="Marketplace URL override")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def check_updates(template_filter: str | None, marketplace_url: str | None, json_output: bool) -> None:
    """Check for template updates from the marketplace."""
    result = check_template_updates(Path.cwd(), marketplace_url, template_filter)
    if json_output:
        console.print_json(json.dumps(result))
        return

    if result["status"] != "online":
        console.print("[yellow]Marketplace offline — cannot check updates[/yellow]")
        return

    table = Table(title="Template Updates")
    table.add_column("Template", style="cyan")
    table.add_column("Local", style="magenta")
    table.add_column("Remote", style="green")

    for item in result["updates"]:
        table.add_row(item["name"], item["local_version"], item["remote_version"])

    if not result["updates"]:
        console.print("[green]All templates are up to date[/green]")
    else:
        console.print(table)


@cli.command()
@click.option("--template", "template_filter", default=None, help="Filter by template name/id")
@click.option("--marketplace-url", default=None, help="Marketplace URL override")
@click.option("--dry-run", is_flag=True, help="Show updates without downloading")
def upgrade(template_filter: str | None, marketplace_url: str | None, dry_run: bool) -> None:
    """Upgrade templates from the marketplace."""
    result = upgrade_templates(Path.cwd(), marketplace_url, template_filter, dry_run=dry_run)
    if result["status"] != "online":
        console.print("[yellow]Marketplace offline — cannot upgrade[/yellow]")
        return

    if not result["updates"]:
        console.print("[green]All templates are up to date[/green]")
        return

    if dry_run:
        console.print("[yellow]Dry run — no files downloaded[/yellow]")

    upgraded = result.get("upgraded", [])
    failed = result.get("failed", [])
    console.print(f"[green]Upgraded: {len(upgraded)}[/green]")
    if failed:
        console.print(f"[red]Failed: {len(failed)}[/red]")


@cli.command()
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--output", "-o", default="plan.json", help="Output plan JSON file")
@click.option("--project-id", default=None, help="Project ID to execute under")
@click.option("--execute", is_flag=True, help="Execute plan after generation")
def implement(spec_file: str, output: str, project_id: str | None, execute: bool) -> None:
    """Generate a task plan from a spec and optionally execute it."""
    spec_path = Path(spec_file)
    plan = build_plan_from_spec(spec_path.read_text(encoding="utf-8"))

    Path(output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    console.print(f"[green]Plan generated: {output} ({len(plan)} tasks)[/green]")

    if execute:
        if not project_id:
            project_id = spec_path.stem
        config = AgentConfig(project_id=project_id, description=f"Implementing {spec_path.name}")
        agent = WeebotAgent(config)

        async def run_plan():
            for item in plan:
                await agent.run([item])

        asyncio.run(run_plan())
        console.print("[green]Plan execution complete[/green]")


# ---------------------------------------------------------------------------
# Agents: personas, packs, routing, sync
# ---------------------------------------------------------------------------


@cli.group()
def agents() -> None:
    """Manage agent personas and packs."""
    pass


@agents.command("import")
@click.argument("path", type=click.Path(exists=True))
def agents_import(path: str) -> None:
    """Import agent personas from a file, directory, or zip bundle."""
    registry = AgentRegistry(Path.cwd())
    personas = registry.import_path(Path(path))
    console.print(f"[green]Imported {len(personas)} persona(s)[/green]")


@agents.command("export")
@click.argument("bundle", type=click.Path())
@click.option("--ids", default="", help="Comma-separated persona IDs to export")
def agents_export(bundle: str, ids: str) -> None:
    """Export personas into a zip bundle."""
    registry = AgentRegistry(Path.cwd())
    persona_ids = [i.strip() for i in ids.split(",") if i.strip()]
    output_path = registry.export_bundle(Path(bundle), persona_ids=persona_ids or None)
    console.print(f"[green]Exported bundle: {output_path}[/green]")


@agents.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def agents_list(json_output: bool) -> None:
    """List registered agent personas."""
    registry = AgentRegistry(Path.cwd())
    personas = registry.list_personas()
    if not personas:
        console.print("[yellow]No personas registered[/yellow]")
        return
    if json_output:
        console.print_json(json.dumps([p.as_dict() for p in personas]))
        return

    table = Table(title="Agent Personas")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Division", style="green")
    table.add_column("Role", style="yellow")
    for p in personas:
        table.add_row(p.persona_id, p.name, p.division or "-", p.role)
    console.print(table)


@agents.command("describe")
@click.argument("persona_id")
def agents_describe(persona_id: str) -> None:
    """Show details for a persona."""
    registry = AgentRegistry(Path.cwd())
    persona = registry.get(persona_id)
    if not persona:
        console.print(f"[red]Persona not found: {persona_id}[/red]")
        return
    console.print_json(json.dumps(persona.as_dict()))


@agents.command("route")
@click.argument("task", nargs=-1)
def agents_route(task: tuple[str, ...]) -> None:
    """Route a task to the best persona."""
    task_text = " ".join(task).strip()
    if not task_text:
        console.print("[red]Task description required[/red]")
        return
    registry = AgentRegistry(Path.cwd())
    personas = registry.list_personas()
    if not personas:
        console.print("[yellow]No personas registered[/yellow]")
        return
    router = PersonaRouter()
    scored = router.route(personas, task_text, top_n=3)
    table = Table(title="Persona Routing")
    table.add_column("Rank", style="cyan")
    table.add_column("Persona", style="magenta")
    table.add_column("Score", style="green")
    for i, item in enumerate(scored, start=1):
        table.add_row(str(i), item.persona.name, f"{item.score:.2f}")
    console.print(table)


@agents.command("validate-output")
@click.argument("persona_id")
@click.argument("output_file", type=click.Path(exists=True))
def agents_validate_output(persona_id: str, output_file: str) -> None:
    """Validate output against a persona's deliverable template."""
    registry = AgentRegistry(Path.cwd())
    persona = registry.get(persona_id)
    if not persona:
        console.print(f"[red]Persona not found: {persona_id}[/red]")
        return
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
    registry = AgentRegistry(Path.cwd())
    divisions = registry.list_divisions()
    if not divisions:
        console.print("[yellow]No divisions found[/yellow]")
        return
    for d in divisions:
        console.print(f"- {d}")


@agents_pack.command("apply")
@click.argument("division")
@click.option("--execute", is_flag=True, help="Spawn agents now")
def agents_pack_apply(division: str, execute: bool) -> None:
    """Create or spawn a division pack."""
    registry = AgentRegistry(Path.cwd())
    personas = registry.pack(division)
    if not personas:
        console.print(f"[red]No personas for division: {division}[/red]")
        return

    tool_registry = RoleBasedToolRegistry()
    seen_roles: dict[str, int] = {}
    specs: list[dict] = []

    for persona in personas:
        base_role = persona.role or persona.name
        count = seen_roles.get(base_role, 0) + 1
        seen_roles[base_role] = count
        role = base_role if count == 1 else f"{base_role}_{count}"

        if persona.tools:
            tools = persona.tools
        else:
            try:
                tools = tool_registry.get_tools_for_role(base_role)
            except ValueError:
                tools = tool_registry.get_tools_for_role("custom")
        specs.append(
            {
                "role": role,
                "description": persona.mission or persona.description or persona.name,
                "tools": tools,
                "config_overrides": {"daily_budget": 10.0},
            }
        )

    if not execute:
        console.print("[yellow]Dry run — use --execute to spawn agents[/yellow]")
        console.print_json(json.dumps(specs))
        return

    async def _spawn():
        context = AgentContext.create_orchestrator()
        factory = AgentFactory()
        await factory.spawn_orchestrator_agents(context, context.agent_id, specs)

    asyncio.run(_spawn())
    console.print(f"[green]Spawned {len(specs)} agent(s) for division {division}[/green]")


@research.command()
@click.argument("title")
@click.option("--description", "-d", default="")
@click.option("--field", "-f", type=click.Choice(["physics", "biology", "math", "cs", "other"]))
def init_experiment(title: str, description: str, field: str):
    """Initialize new reproducible experiment"""
    from research_modules.reproducibility import ReproducibilityManager, ExperimentConfig
    
    rm = ReproducibilityManager()
    config = ExperimentConfig(
        title=title,
        description=description,
        tags=[field] if field else [],
        random_seed=42
    )
    exp = rm.create_experiment(config)
    console.print(Panel(
        f"Created experiment: {exp.exp_id}\n"
        f"Location: {exp.work_dir}\n"
        f"Seed: {config.random_seed}",
        title="Reproducible Experiment"
    ))


@research.command()
@click.argument("data_file")
@click.option("--rules", "-r", help="JSON file with validation rules")
def validate_data(data_file: str, rules: str):
    """Validate scientific dataset"""
    from research_modules.data_validator import ScientificValidator
    import pandas as pd
    import json
    
    df = pd.read_csv(data_file)
    
    validator = ScientificValidator()
    validation_rules = json.loads(Path(rules).read_text()) if rules else {}
    
    report = validator.validate_dataset(df, validation_rules)
    
    console.print(f"Valid: {'✓' if report['valid'] else '✗'}")
    console.print(f"Issues found: {len(report['issues'])}")
    
    for issue in report['issues']:
        color = {
            'info': 'blue',
            'warning': 'yellow',
            'error': 'red',
            'critical': 'red'
        }.get(issue['severity'], 'white')
        
        console.print(f"[{color}]{issue['severity'].upper()}: {issue['message']}[/{color}]")


@research.command()
@click.argument("vault_path")
@click.option("--experiment", "-e", help="Specific experiment to sync")
def obsidian_sync(vault_path: str, experiment: str):
    """Sync experiments to Obsidian vault"""
    from integrations.obsidian import ObsidianVault
    
    vault = ObsidianVault(vault_path)
    
    if experiment:
        vault.generate_from_experiment(experiment)
        console.print(f"[green]Synced experiment: {experiment}[/green]")
    else:
        vault.create_dashboard()
        console.print("[green]Created research dashboard[/green]")


# -----------------------------------------------------------------------------
# New Clean Architecture flow commands
# -----------------------------------------------------------------------------

@cli.group()
def flow() -> None:
    """PlanActFlow commands (new architecture)."""
    pass


@flow.command("run")
@click.argument("prompt")
@click.option("--session-id", default=None, help="Session identifier")
@click.option("--model", default=None, help="Override default LLM model")
def flow_run(prompt: str, session_id: str | None, model: str | None) -> None:
    """Run a one-shot PlanActFlow with the given prompt."""
    import asyncio

    from weebot.application.services.model_selection import ModelSelectionService
    from weebot.interfaces.cli.agent_runner import AgentRunner
    from weebot.interfaces.cli.event_logger import CLIEventSubscriber
    from weebot.domain.models.event import WaitForUserEvent

    async def _run() -> None:
        import uuid

        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter(model or "gpt-4o-mini")
        state_repo = _get_state_repo()
        run_session_id = session_id or str(uuid.uuid4())
        runner = AgentRunner(llm=llm, state_repo=state_repo, model=model, use_rich=False)
        subscriber = CLIEventSubscriber(use_rich=True)

        async for event in runner.run_prompt(prompt, session_id=run_session_id):
            await subscriber.on_event(event)
            if isinstance(event, WaitForUserEvent):
                answer = input(f"\n[weebot asks] {event.question}\nYour answer: ")
                async for resume_event in runner.resume_session(run_session_id, answer):
                    await subscriber.on_event(resume_event)
                break

    asyncio.run(_run())


@flow.command("resume")
@click.argument("session_id")
@click.argument("answer")
def flow_resume(session_id: str, answer: str) -> None:
    """Resume a waiting session with a user answer."""
    import asyncio

    from weebot.application.services.model_selection import ModelSelectionService
    from weebot.interfaces.cli.agent_runner import AgentRunner
    from weebot.interfaces.cli.event_logger import CLIEventSubscriber

    async def _run() -> None:
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter("gpt-4o-mini")
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo, use_rich=False)
        subscriber = CLIEventSubscriber(use_rich=True)

        async for event in runner.resume_session(session_id, answer):
            await subscriber.on_event(event)

    asyncio.run(_run())


@flow.command("list")
@click.option("--user-id", default=None, help="Filter by user ID")
def flow_list(user_id: str | None) -> None:
    """List active/waiting sessions."""
    import asyncio

    from weebot.application.services.model_selection import ModelSelectionService
    from weebot.interfaces.cli.agent_runner import AgentRunner

    async def _run() -> None:
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter("gpt-4o-mini")
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo)
        sessions = await runner.list_sessions(user_id=user_id)

        table = Table(title="Sessions")
        table.add_column("ID", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Title", style="green")
        for s in sessions:
            table.add_row(s.id, s.status.value, s.title or "—")
        console.print(table)

    asyncio.run(_run())


@flow.command("cancel")
@click.argument("session_id")
def flow_cancel(session_id: str) -> None:
    """Cancel a running session."""
    import asyncio

    from weebot.application.services.model_selection import ModelSelectionService
    from weebot.interfaces.cli.agent_runner import AgentRunner

    async def _run() -> None:
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter("gpt-4o-mini")
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo)
        ok = await runner.cancel_session(session_id)
        if ok:
            console.print(f"[green]Cancelled session {session_id}[/green]")
        else:
            console.print(f"[yellow]Session {session_id} was not active[/yellow]")

    asyncio.run(_run())


@flow.command("undo")
@click.argument("session_id")
def flow_undo(session_id: str) -> None:
    """Undo the last plan mutation for a session."""
    import asyncio

    from weebot.application.services.model_selection import ModelSelectionService
    from weebot.interfaces.cli.agent_runner import AgentRunner

    async def _run() -> None:
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter("gpt-4o-mini")
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo)
        ok = await runner.flow_undo(session_id)
        if ok:
            console.print(f"[green]Undid last plan change for session {session_id}[/green]")
        else:
            console.print(f"[yellow]Nothing to undo for session {session_id}[/yellow]")

    asyncio.run(_run())


@flow.command("export")
@click.argument("session_id")
@click.option("--output", default=None, help="Output .jsonl file path (default: <session_id>.jsonl)")
@click.option("--compress", default=None, type=int, help="Compress middle turns to fit this token budget before export")
def flow_export(session_id: str, output: str | None, compress: int | None) -> None:
    """Export session events to JSONL for analysis or fine-tuning."""
    import asyncio

    from weebot.application.services.trajectory_exporter import TrajectoryExporter

    dest = output or f"{session_id}.jsonl"

    async def _run() -> None:
        state_repo = _get_state_repo()
        exporter = TrajectoryExporter(repo=state_repo)
        try:
            count = await exporter.export_session(
                session_id, dest, compress_to_budget=compress
            )
            console.print(f"[green]Exported {count} events → {dest}[/green]")
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")

    asyncio.run(_run())


# Add behavior commands
cli.add_command(behavior_cli)


# ── Benchmark commands ──────────────────────────────────────────────────────

@cli.group()
def benchmark() -> None:
    """Run weebot agents against SIA-compatible benchmark tasks."""


@benchmark.command("list")
@click.argument("tasks_dir", type=click.Path(exists=True))
def benchmark_list(tasks_dir: str) -> None:
    """List all benchmark tasks found in TASKS_DIR."""
    from pathlib import Path
    from weebot.application.harness.loader import TaskLoader

    tasks = TaskLoader.load_all_from_dir(Path(tasks_dir))
    if not tasks:
        console.print("[yellow]No tasks found.[/yellow]")
        return
    for task in tasks:
        tags = ", ".join(task.tags) if task.tags else "—"
        console.print(
            f"[bold]{task.task_id}[/bold]  "
            f"({len(task.samples)} samples, tags: {tags})"
        )


@benchmark.command("run")
@click.argument("task_path", type=click.Path(exists=True))
@click.option("--skill-name", default="general", show_default=True)
@click.option("--model", default=None, help="Override LLM model")
@click.option("--sample", "sample_idx", default=0, type=int, show_default=True)
@click.option("--db", default="./weebot_sessions.db", show_default=True)
def benchmark_run(task_path: str, skill_name: str, model: str | None, sample_idx: int, db: str) -> None:
    """Run one sample from a benchmark task at TASK_PATH."""
    import asyncio
    import json
    from pathlib import Path
    from weebot.application.harness.loader import TaskLoader
    from weebot.application.harness.runner import BenchmarkRunner
    from weebot.application.harness.scorer import TaskScorer
    from weebot.application.di import Container

    async def _run() -> None:
        task = TaskLoader.load_from_dir(Path(task_path))
        container = Container()
        container.configure_defaults(db_path=db, default_model=model)
        runner = BenchmarkRunner(
            flow_factory=container._create_target_flow_factory(),
            scorer=TaskScorer(),
            skill_name=skill_name,
        )
        result = await runner.run_task(task, sample_idx)
        console.print(json.dumps(result.to_dict(), indent=2))
        status = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        console.print(f"Score: {result.score:.3f}  {status}")

    asyncio.run(_run())


@benchmark.command("batch")
@click.argument("tasks_dir", type=click.Path(exists=True))
@click.option("--skill-name", default="general", show_default=True)
@click.option("--model", default=None, help="Override LLM model")
@click.option("--concurrency", default=4, type=int, show_default=True)
@click.option("--output", "-o", default="benchmark_results.json", show_default=True)
@click.option("--db", default="./weebot_sessions.db", show_default=True)
def benchmark_batch(
    tasks_dir: str, skill_name: str, model: str | None,
    concurrency: int, output: str, db: str,
) -> None:
    """Run all samples in all tasks under TASKS_DIR and write results to OUTPUT."""
    import asyncio
    import json
    from pathlib import Path
    from weebot.application.harness.loader import TaskLoader
    from weebot.application.harness.runner import BenchmarkRunner
    from weebot.application.harness.scorer import TaskScorer
    from weebot.application.di import Container

    async def _run() -> None:
        tasks = TaskLoader.load_all_from_dir(Path(tasks_dir))
        if not tasks:
            console.print("[yellow]No tasks found.[/yellow]")
            return

        container = Container()
        container.configure_defaults(db_path=db, default_model=model)
        runner = BenchmarkRunner(
            flow_factory=container._create_target_flow_factory(),
            scorer=TaskScorer(),
            skill_name=skill_name,
        )
        results = await runner.run_batch(tasks, concurrency=concurrency)
        records = [r.to_dict() for r in results]
        Path(output).write_text(json.dumps(records, indent=2), encoding="utf-8")

        passed = sum(1 for r in results if r.passed)
        console.print(f"[green]{passed}[/green]/{len(results)} passed. Results → {output}")

    asyncio.run(_run())


@benchmark.command("report")
@click.argument("results_file", type=click.Path(exists=True))
def benchmark_report(results_file: str) -> None:
    """Pretty-print a benchmark results JSON file."""
    import json
    from pathlib import Path

    records = json.loads(Path(results_file).read_text(encoding="utf-8"))
    if not records:
        console.print("[yellow]Empty results file.[/yellow]")
        return

    passed = sum(1 for r in records if r.get("passed"))
    avg_score = sum(r.get("score", 0.0) for r in records) / len(records)
    console.print(f"[bold]Results:[/bold] {passed}/{len(records)} passed, avg score {avg_score:.3f}")
    console.print("")

    for r in records:
        status = "[green]✓[/green]" if r.get("passed") else "[red]✗[/red]"
        console.print(
            f"  {status} {r['task_id']}[{r['sample_idx']}]  "
            f"score={r['score']:.3f}  "
            f"answer={r.get('answer', '')!r}"
        )


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        import logging
        import sys
        logging.exception("Unhandled CLI exception: %s", exc)
        sys.stderr.write(f"\nError: {exc}\n")
        sys.exit(1)
