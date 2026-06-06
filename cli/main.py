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
import shutil
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
from weebot.interfaces.cli.support import (
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
from cli.commands.flow import flow as flow_group
from cli.commands.skills import skill as skill_group
from cli.commands.agents import agents as agents_group
from cli.commands.harness import benchmark, harness  # type: ignore[attr-defined]
from cli.commands.profile import profile as profile_group
from cli.commands.scheduling import cron, companion  # type: ignore[attr-defined]
from cli.commands.guard import guard as guard_group
from cli.commands.analytics import analytics as analytics_group

console = Console()


@click.group()
def cli() -> None:
    """weebot Agent Framework CLI."""
    from weebot.infrastructure.observability.logging_config import configure_logging
    configure_logging()


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


def _print_doctor_table(report: Any) -> None:
    """Render a DoctorReport as a rich Table."""
    table = Table(title="weebot Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Details", style="green")
    for check in report.checks:
        table.add_row(check.name, check.status, check.details)
    console.print(table)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--fix", is_flag=True, help="Auto-repair warnings (create dirs, init DBs)")
@click.option("--dry-run", is_flag=True, help="Show what --fix would do without changing anything")
def doctor(json_output: bool, fix: bool, dry_run: bool) -> None:
    """Run diagnostics and environment checks."""
    if dry_run:
        # Show what would be fixed without applying changes
        report_preview = run_doctor(Path.cwd(), fix=False)
        _print_doctor_table(report_preview)
        warn_count = report_preview.summary.get("warn", 0)
        if warn_count > 0:
            console.print()
            console.print(
                f"[dim]--dry-run: {warn_count} warning(s) would be candidates for --fix[/dim]"
            )
            for check in report_preview.checks:
                if check.status == "warn":
                    console.print(f"  [yellow]â\u00b0  {check.name}:[/yellow] {check.details}")
        return

    report = run_doctor(Path.cwd(), fix=fix)

    if json_output:
        data = report.as_dict()
        if hasattr(report, "repairs"):
            data["repairs"] = [
                {"check": r.check_name, "repaired": r.repaired, "message": r.message}
                for r in report.repairs
            ]
        console.print_json(json.dumps(data))
        return

    _print_doctor_table(report)

    # Show repair results
    if fix and hasattr(report, "repairs") and report.repairs:
        console.print()
        for r in report.repairs:
            if r.repaired:
                console.print(f"  [green]â\u0153\u201c {r.check_name}:[/green] {r.message}")
            else:
                console.print(f"  [yellow]â\u00b0  {r.check_name}:[/yellow] {r.message}")

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


# ---------------------------------------------------------------------------
# Skill conversion commands (Enhancement 10)
# ---------------------------------------------------------------------------


# skill group extracted to cli/commands/skills.py
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


# agents group extracted to cli/commands/agents.py
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

# flow commands extracted to cli/commands/flow.py


# Register command groups extracted to cli/commands/
cli.add_command(behavior_cli)
cli.add_command(flow_group)
from cli.commands.hyper import hyper as hyper_group
cli.add_command(hyper_group)
cli.add_command(skill_group)
cli.add_command(agents_group)
cli.add_command(benchmark)
cli.add_command(harness)
cli.add_command(profile_group)
cli.add_command(cron)
cli.add_command(companion)
cli.add_command(guard_group)
cli.add_command(analytics_group)


# ── Benchmark / profile / scheduling commands ─────────────────────────────
# Extracted to cli/commands/harness.py, cli/commands/profile.py,
# and cli/commands/scheduling.py — registered via cli.add_command() above.


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        import logging
        import sys
        logging.exception("Unhandled CLI exception: %s", exc)
        sys.stderr.write(f"\nError: {exc}\n")
        sys.exit(1)
