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
import sys

# ── Force UTF-8 stdio (must run before any click/print output) ─────────
# Windows consoles default stdout/stderr to the system codepage (e.g.
# cp1253 on Greek locale), which cannot encode characters like the '→'
# used throughout CLI help text and log messages — this crashes every
# command's --help with UnicodeEncodeError on non-English Windows locales.
# errors="replace" degrades to '?' instead of crashing if a console still
# can't render a glyph after the encoding fix.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import click
import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

# ── Load .env into os.environ before any weebot module reads API keys ──
# pydantic-settings loads .env into its own store but does NOT populate
# os.environ.  Several modules (openai_adapter.py, model_registry/_service.py,
# browser_tool.py, image_gen_tool.py, openrouter_enhanced_cascade.py) read
# keys via bare os.getenv().  Without this call, those paths get None when
# keys live solely in .env, resulting in "no-key" → 401 from providers.
#
# override=True: .env values take priority over stale system environment
# variables (e.g. an old OPENROUTER_API_KEY from a previous session).
from dotenv import load_dotenv
load_dotenv(override=True)

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


def _get_llm() -> Any:
    """Resolve LLMPort from the shared DI container for health checks."""
    global _container
    if _container is None:
        _container = Container()
        _container.configure_defaults()
    from weebot.application.ports.llm_port import LLMPort
    return _container.get(LLMPort)
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress



# _deprecated_agent() and the 5 [DEPRECATED] CLI commands were removed
# in ARCH-AUDIT-V2 (agent_core_v2 sunset). Use 'weebot flow *' commands instead.
# See cli/commands/flow.py for the replacement commands.
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
# agent_factory.py sunset in ARCH-AUDIT-V2 A5
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
from cli.commands.soul import soul as soul_group
from cli.commands.ponytail import (
    cmd_ponytail,
    cmd_ponytail_review,
    cmd_ponytail_audit,
    cmd_ponytail_help,
)

console = Console()


@click.group()
def cli() -> None:
    """weebot Agent Framework CLI."""
    from weebot.infrastructure.observability.logging_config import configure_logging
    configure_logging()


@cli.result_callback()
def _handle_cli_exceptions(result, **kwargs):
    """Catch unhandled exceptions and return structured CLI errors."""
    pass  # Click's built-in exception handling is sufficient for CLI


def _wrap_main() -> None:
    """Entry-point wrapper with global exception handling."""
    import sys
    from weebot.domain.exceptions import WeebotError
    try:
        cli()
    except WeebotError as exc:
        from rich.console import Console
        console = Console()
        console.print(f"[red]Error [/{exc.code.value if exc.code else 'unknown'}]: {exc.message}[/red]")
        sys.exit(1)
    except Exception as exc:
        from rich.console import Console
        console = Console()
        console.print(f"[red]Unexpected error: {exc}[/red]")
        sys.exit(1)

@cli.command()
@click.argument("project_id")
@click.argument("description")
def create(project_id: str, description: str) -> None:
    """[DEPRECATED] Use 'flow run' instead. Create new project."""
    console.print(f"[yellow]Command 'create' is deprecated. Use 'flow run' instead.[/yellow]")


@cli.command()
def list_projects() -> None:
    """[DEPRECATED] Use 'flow' commands instead. List all projects."""
    state_repo = _get_state_repo()
    sessions = asyncio.run(state_repo.list_sessions())

    table = Table(title="Active Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Created", style="green")

    for session in sessions:
        table.add_row(
            session.session_id,
            session.status.value if session.status else "unknown",
            str(session.created_at) if session.created_at else "-",
        )

    console.print(table)


@cli.command()
@click.argument("project_id")
def status(project_id: str) -> None:
    """[DEPRECATED] Use 'flow list' instead. Check project status."""
    console.print(f"[yellow]Command 'status' is deprecated. Use 'flow list' instead.[/yellow]")


@cli.command()
@click.argument("project_id")
@click.argument("plan_file", type=click.Path(exists=True))
def run(project_id: str, plan_file: str) -> None:
    """[DEPRECATED] Use 'flow run' instead. Execute task plan from JSON file."""
    console.print(f"[yellow]Command 'run' is deprecated. Use 'flow run' instead.[/yellow]")


@cli.command()
@click.argument("project_id")
def resume(project_id: str) -> None:
    """[DEPRECATED] Use 'flow resume' instead. Resume paused project."""
    console.print(f"[yellow]Command 'resume' is deprecated. Use 'flow resume' instead.[/yellow]")


@cli.command()
@click.argument("project_id")
@click.argument("checkpoint_id")
@click.argument("response")
def checkpoint(project_id: str, checkpoint_id: str, response: str) -> None:
    """[DEPRECATED] Use 'flow' commands instead. Resolve pending checkpoint."""
    console.print(f"[yellow]Command 'checkpoint' is deprecated. Use 'flow' commands instead.[/yellow]")


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
    state_repo = _get_state_repo()
    session = asyncio.run(state_repo.load_session(project_id))

    if session:
        import json
        from pydantic import BaseModel

        Path(output).write_text(
            json.dumps(session.model_dump(), indent=2, default=str)
        )
        console.print(f"[green]Exported to: {output}[/green]")
    else:
        console.print(f"[red]Session not found: {project_id}[/red]")


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


def _validate_model_catalog(json_output: bool) -> None:
    """Cross-validate cascade models against the model catalog."""
    from weebot.config._catalog_validator import CatalogValidator

    _report = CatalogValidator.run_default_validation()
    if json_output:
        import json as _json
        console.print_json(_json.dumps({
            "ok": _report.warning_count == 0,
            "total_models_checked": _report.total_models_checked,
            "elapsed_ms": round(_report.elapsed_ms, 1),
            "warnings": [
                {"model_id": w.model_id, "cascade_role": w.cascade_role, "field": w.field, "detail": str(w)}
                for w in _report.warnings
            ],
        }))
        return
    if _report.warning_count == 0:
        console.print(
            f"[green]Catalog validation passed:[/green] "
            f"{_report.total_models_checked} models checked, 0 warnings "
            f"({_report.elapsed_ms:.0f}ms)"
        )
    else:
        console.print(
            f"[yellow]Catalog validation: {_report.warning_count} warning(s)[/yellow] "
            f"({_report.total_models_checked} models, {_report.elapsed_ms:.0f}ms)"
        )
        for w in _report.warnings:
            console.print(f"  [yellow]![/yellow] {w}")


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
@click.option("--validate-catalog", is_flag=True, help="Cross-validate cascade models against the model catalog")
def doctor(json_output: bool, fix: bool, dry_run: bool, validate_catalog: bool) -> None:
    """Run diagnostics and environment checks."""

    # -- standalone: --validate-catalog ----------------------------------------
    if validate_catalog:
        _validate_model_catalog(json_output)
        return

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

        # ── Model health ping ────────────────────────────────────
        from weebot.core.model_health import check_default_model
        from weebot.config.model_refs import MODEL_CASCADE_TIER1
        model_ok = await check_default_model(
            _get_llm(), MODEL_CASCADE_TIER1, timeout=10.0
        )

        if json_output:
            data = report.to_dict()
            data["model_health"] = {
                "model": MODEL_CASCADE_TIER1,
                "reachable": model_ok,
            }
            console.print_json(json.dumps(data))
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

        # Model health row
        model_status = HealthStatus.HEALTHY if model_ok else HealthStatus.UNHEALTHY
        model_color = status_colors.get(model_status, "white")
        table.add_row(
            f"Model ({MODEL_CASCADE_TIER1})",
            f"[{model_color}]{model_status.value}[/{model_color}]",
            "—",
            "Reachable" if model_ok else "UNREACHABLE — check API key and credits",
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
def implement(spec_file: str, output: str) -> None:
    """Generate a task plan from a spec.

    The --execute flag was removed (agent_core_v2 sunset).
    Use 'weebot flow run' to execute the generated plan.
    """
    spec_path = Path(spec_file)
    plan = build_plan_from_spec(spec_path.read_text(encoding="utf-8"))

    Path(output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    console.print(f"[green]Plan generated: {output} ({len(plan)} tasks)[/green]")
    console.print("[dim]Use 'weebot flow run' to execute this plan.[/dim]")


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
cli.add_command(soul_group)
from cli.commands.dream import dream as dream_group
cli.add_command(dream_group)
from cli.commands.mcp import mcp as mcp_group
cli.add_command(mcp_group)
from cli.commands.gateway import gateway as gateway_group
cli.add_command(gateway_group)
from cli.commands.cron_agent import cron_agent as cron_agent_group
cli.add_command(cron_agent_group)

# Auth (multi-principal key management)
from cli.commands.auth import auth_group
cli.add_command(auth_group)

# Ponytail lazy-senior-dev commands
cli.add_command(cmd_ponytail)
cli.add_command(cmd_ponytail_review)
cli.add_command(cmd_ponytail_audit)
cli.add_command(cmd_ponytail_help)


# ── Benchmark / profile / scheduling commands ─────────────────────────────
# Extracted to cli/commands/harness.py, cli/commands/profile.py,
# and cli/commands/scheduling.py — registered via cli.add_command() above.


if __name__ == "__main__":
    _wrap_main()
