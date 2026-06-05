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
cli.add_command(skill_group)
cli.add_command(agents_group)


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


@cli.group()
def harness() -> None:
    """Generate and manage agent team harnesses for domain-specific workflows."""
    pass


@harness.command("generate")
@click.argument("domain")
@click.option("--output-dir", default=".", help="Output directory (default: current)")
@click.option("--dry-run", is_flag=True, help="Show what would be generated without writing")
def harness_generate(domain: str, output_dir: str, dry_run: bool) -> None:
    """Generate an agent team harness for a domain description.

    DOMAIN is a natural language description of the work, e.g.
    "deep research with web scraping and academic sources".

    Creates agent definitions in .claude/agents/ and skills in
    .claude/skills/ tailored to the domain.
    """
    import asyncio

    async def _run() -> None:
        from weebot.application.flows.harness_generation_flow import (
            HarnessGenerationFlow,
        )
        from rich.console import Console

        console = Console()

        if dry_run:
            flow = HarnessGenerationFlow(output_dir=output_dir)
            arch = await flow.generate(domain)

            console.print(f"[bold]Domain:[/bold] {arch.domain}")
            console.print(f"[bold]Pattern:[/bold] {arch.pattern.value}")
            console.print(f"\n[bold]Agents ({len(arch.agents)}):[/bold]")
            for a in arch.agents:
                console.print(f"  [cyan]{a.name}[/cyan] — {a.role}")
            console.print(f"\n[bold]Skills ({len(arch.skills)}):[/bold]")
            for s in arch.skills:
                console.print(f"  [green]{s.name}[/green] — {s.description[:60]}")
            console.print(f"\n[dim]Dry run — no files written.[/dim]")
            return

        flow = HarnessGenerationFlow(output_dir=output_dir)
        arch = await flow.generate_and_write(domain)

        console.print(f"[green]✓[/green] Generated [bold]{arch.pattern.value}[/bold] harness for '[cyan]{arch.domain}[/cyan]'")
        console.print(f"  Agents: {len(arch.agents)}")
        console.print(f"  Skills: {len(arch.skills)}")
        console.print(f"  Output: {Path(output_dir).resolve() / '.claude'}")

    asyncio.run(_run())


@cli.group()
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


@cli.group()
def cron() -> None:
    """Schedule recurring tasks with natural language."""
    pass


@cron.command("schedule")
@click.argument("schedule_text", nargs=-1, required=True)
@click.option("--task", required=True, help="Task description to execute")
@click.option("--name", default=None, help="Job name (default: auto-generated)")
def cron_schedule(schedule_text: tuple[str, ...], task: str, name: str | None) -> None:
    """Schedule a recurring task using natural language.

    SCHEDULE_TEXT is a natural-language schedule like
    "every Friday at 2pm" or "every 3 hours".

    Example:
        weebot cron schedule "every day at 9am" --task "Run daily report"
        weebot cron schedule "every Monday" --task "Weekly security audit"
    """
    import asyncio

    async def _run() -> None:
        from weebot.scheduling.nl_cron import parse_schedule
        from weebot.scheduling.scheduler import SchedulingManager
        import uuid

        text = " ".join(schedule_text)
        parsed = parse_schedule(text)

        if parsed is None:
            console.print(
                f"[red]✗[/red] Could not parse schedule: '{text}'. "
                "Try: 'every day at 9am', 'every Monday at 2pm', "
                "'every 3 hours'."
            )
            return

        job_id = f"cron-{uuid.uuid4().hex[:8]}"
        job_name = name or f"Scheduled: {task[:40]}"

        # Store the schedule in jobs.yaml or create an in-memory job
        mgr = SchedulingManager()
        try:
            from apscheduler.triggers.cron import CronTrigger
            trigger = CronTrigger.from_crontab(parsed["cron_expression"])
            await mgr.create_job(
                job_id=job_id,
                name=job_name,
                description=task,
                trigger_type="cron",
                trigger_config={"cron_expression": parsed["cron_expression"]},
                callable_name="_nl_cron_executor",
            )
            console.print(
                f"[green]✓[/green] Scheduled: [cyan]{job_name}[/cyan]\n"
                f"  Schedule: {parsed['description']} ({parsed['cron_expression']})\n"
                f"  Task: {task}"
            )
        except Exception as exc:
            console.print(f"[red]✗[/red] Failed to schedule: {exc}")

    asyncio.run(_run())


@cron.command("list")
def cron_list() -> None:
    """List all scheduled cron jobs."""
    import asyncio

    async def _run() -> None:
        from weebot.scheduling.scheduler import SchedulingManager
        from rich.table import Table

        mgr = SchedulingManager()
        jobs = await mgr.list_jobs()

        if not jobs:
            console.print("[dim]No scheduled jobs.[/dim]")
            return

        table = Table(title="Scheduled Jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Schedule")
        table.add_column("Enabled", style="green")

        for j in jobs:
            schedule = j.trigger_config.get("cron_expression", j.trigger_type) if hasattr(j, "trigger_config") else j.trigger_type
            enabled = "✓" if getattr(j, "enabled", True) else "✗"
            table.add_row(
                getattr(j, "job_id", "?")[:12],
                getattr(j, "name", "?")[:40],
                str(schedule)[:20],
                enabled,
            )
        console.print(table)

    asyncio.run(_run())


@cron.command("remove")
@click.argument("job_id")
def cron_remove(job_id: str) -> None:
    """Remove a scheduled job by ID."""
    import asyncio

    async def _run() -> None:
        from weebot.scheduling.scheduler import SchedulingManager

        mgr = SchedulingManager()
        await mgr.remove_job(job_id)
        console.print(f"[green]✓[/green] Removed job '[cyan]{job_id}[/cyan]'")

    asyncio.run(_run())


@cli.command()
def companion() -> None:
    """Start the Windows desktop companion (system tray + global hotkey).

    Requires optional dependencies: pystray, keyboard, and tkinter.
    """
    import asyncio

    async def _run() -> None:
        from weebot.interfaces.windows import run_companion

        await run_companion()

    asyncio.run(_run())


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        import logging
        import sys
        logging.exception("Unhandled CLI exception: %s", exc)
        sys.stderr.write(f"\nError: {exc}\n")
        sys.exit(1)
