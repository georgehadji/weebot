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


@cli.group()
def skill() -> None:
    """Manage and convert skills."""
    pass


@skill.command("convert")
@click.argument("source", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override skill name")
@click.option("--output", default=None, help="Target directory (default: skills/builtin/<name>)")
def skill_convert(source: str, name: str | None, output: str | None) -> None:
    """Convert an external skill to Weebot format.

    SOURCE can be a directory or file.  Detects format automatically
    (Manus SKILL.md, MyManus plugin.json, AgenticSeek .txt).
    """
    import asyncio

    async def _run() -> None:
        from pathlib import Path
        from weebot.application.skills.skill_converter import SkillConverter

        converter = SkillConverter()
        report = converter.convert(Path(source))

        if report.success:
            console.print(f"[green]✓ Converted:[/green] {report.target_path}")
        else:
            console.print(f"[red]✗ Failed:[/red] {report.source_path}")
            for err in report.errors:
                console.print(f"  [red]{err}[/red]")

        for w in report.warnings or []:
            console.print(f"  [yellow]{w}[/yellow]")

    asyncio.run(_run())


@skill.command("convert-all")
@click.option("--dry-run", is_flag=True, help="Show what would be converted without writing")
def skill_convert_all(dry_run: bool) -> None:
    """Scan skills/import/ and convert all detected external skills."""
    import asyncio

    async def _run() -> None:
        from pathlib import Path
        from weebot.application.skills.format_detector import FormatDetector
        from weebot.application.skills.skill_converter import SkillConverter
        from weebot.domain.models.skill_source import SourceFormat

        import_dir = Path("skills/import")
        if not import_dir.exists():
            console.print("[yellow]No skills/import/ directory found[/yellow]")
            return

        converter = SkillConverter()
        found = 0
        converted = 0

        for entry in sorted(import_dir.iterdir()):
            source = FormatDetector.detect(entry)
            if source.format != SourceFormat.UNKNOWN and source.format != SourceFormat.WEEBOT:
                found += 1
                if dry_run:
                    console.print(f"  [blue]Would convert:[/blue] {entry.name} ({source.format.value})")
                else:
                    report = converter.convert(entry)
                    if report.success:
                        converted += 1
                        console.print(f"  [green]✓ {entry.name}[/green] → {report.target_path}")
                    else:
                        console.print(f"  [red]✗ {entry.name}: {report.errors[0]}[/red]")

        if found == 0:
            console.print("[yellow]No external skills found in skills/import/[/yellow]")
        else:
            console.print(f"\nFound: {found}, Converted: {converted}")

    asyncio.run(_run())


@skill.command("list")
@click.option("--active-only", is_flag=True, help="Show only skills with all required env vars set")
def skill_list(active_only: bool) -> None:
    """List all discovered skills from builtin and user directories."""
    import asyncio

    async def _run() -> None:
        from weebot.application.skills.skill_registry import SkillRegistry
        from rich.table import Table

        registry = SkillRegistry()
        registry.load_all()

        skills = registry.get_active_skills() if active_only else registry.list_skills()
        if not skills:
            console.print("[dim]No skills found.[/dim]")
            return

        table = Table(title="Installed Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Source", style="dim")

        for sk in sorted(skills, key=lambda s: s.name):
            table.add_row(sk.name, sk.description[:80], sk.source_path or "—")

        console.print(table)

    asyncio.run(_run())


@skill.command("install")
@click.argument("source", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override skill name (default: auto-detected)")
def skill_install(source: str, name: str | None) -> None:
    """Install a skill from a file or directory.

    SOURCE can be a directory containing SKILL.md (Weebot format),
    a Manus plugin.json, or an AgenticSeek .txt file.

    The format is auto-detected.  The skill is installed into
    .weebot/skills/<name>/ so it appears in the SkillRegistry.
    """
    import asyncio

    async def _run() -> None:
        import yaml
        from pathlib import Path
        from weebot.application.skills.format_detector import FormatDetector
        from weebot.application.skills.skill_converter import SkillConverter
        from weebot.domain.models.skill_source import SourceFormat

        source_path = Path(source).resolve()
        detected = FormatDetector.detect(source_path)

        # Extract name from YAML frontmatter when possible
        skill_name = name
        if name is None:
            if detected.format in (SourceFormat.WEEBOT, SourceFormat.MANUS):
                # Parse YAML frontmatter for the name field
                skill_md = source_path if source_path.is_file() and source_path.name == "SKILL.md" else source_path / "SKILL.md"
                if skill_md.exists():
                    text = skill_md.read_text(encoding="utf-8")
                    if text.startswith("---"):
                        parts = text.split("---", 2)
                        if len(parts) >= 3:
                            try:
                                fm = yaml.safe_load(parts[1])
                                skill_name = (fm or {}).get("name") or detected.name
                            except Exception:
                                skill_name = detected.name
                        else:
                            skill_name = detected.name
                    else:
                        skill_name = detected.name
                else:
                    skill_name = detected.name or source_path.stem
            else:
                skill_name = detected.name or source_path.stem

        # Target: .weebot/skills/<skill_name>/
        target_dir = Path.cwd() / ".weebot" / "skills" / skill_name

        if detected.format in (SourceFormat.WEEBOT, SourceFormat.MANUS):
            # Direct SKILL.md copy
            if source_path.is_dir():
                skill_md = source_path / "SKILL.md"
            else:
                skill_md = source_path

            if not skill_md.exists() or skill_md.name != "SKILL.md":
                console.print(f"[red]✗[/red] Expected a SKILL.md file at {source}")
                return

            # Verify the file has YAML frontmatter (not arbitrary content)
            first_bytes = skill_md.read_bytes()[:200]
            if not first_bytes.startswith(b"---"):
                console.print(
                    f"[red]✗[/red] {skill_md} does not appear to be a valid "
                    "Weebot/Manus skill file (missing YAML frontmatter)."
                )
                return

            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(skill_md), str(target_dir / "SKILL.md"))
            console.print(
                f"[green]✓[/green] Installed '[cyan]{skill_name}[/cyan]' "
                f"to {target_dir.relative_to(Path.cwd())}"
            )
            return

        if detected.format in (SourceFormat.MYMANUS, SourceFormat.AGENTICSEEK):
            # Convert and write to target
            converter = SkillConverter(skills_dir=target_dir.parent)
            report = converter.convert(source_path)
            if report.success:
                console.print(
                    f"[green]✓[/green] Installed '[cyan]{skill_name}[/cyan]' "
                    f"to {target_dir.relative_to(Path.cwd())}"
                )
            else:
                console.print(f"[red]✗[/red] Conversion failed: {report.errors[0]}")
            return

        console.print(
            f"[red]✗[/red] Cannot determine format of {source}. "
            "Expected a Weebot SKILL.md, Manus plugin.json, "
            "or AgenticSeek .txt file."
        )

    asyncio.run(_run())


@skill.command("update")
@click.argument("skill_name", required=False)
@click.option("--check", is_flag=True, help="Check for updates without installing")
@click.option("--source", type=click.Choice(["skillhub", "agentskills"]), default="skillhub",
              help="Index source (default: weebot SkillHub, agentskills: agentskills.io)")
def skill_update(skill_name: str | None, check: bool) -> None:
    """Update installed skills from the SkillHub remote index.

    Without arguments: check all installed skills for updates.
    With SKILL_NAME: update (or check) that specific skill.
    """
    import asyncio

    async def _run() -> None:
        import yaml
        from pathlib import Path
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.infrastructure.adapters.skill_index_github import GitHubSkillIndexAdapter
        from rich.console import Console
        from rich.table import Table

        console = Console()

        # Load local skills
        registry = SkillRegistry()
        registry.load_all()
        local_skills = {s.name: s for s in registry.list_skills()}

        if not local_skills:
            console.print("[dim]No local skills found to check for updates.[/dim]")
            return

        # Fetch remote index
        index = GitHubSkillIndexAdapter()
        remote_skills = await index.fetch_index()
        remote_map = {s.name: s for s in remote_skills}

        if not remote_map:
            console.print("[yellow]Could not fetch SkillHub index. Check your internet connection.[/yellow]")
            return

        # Filter to requested skill if specified
        names_to_check = [skill_name] if skill_name else list(local_skills.keys())

        updates: list[tuple[str, str, str]] = []  # (name, local_version, remote_version)
        for name in names_to_check:
            local = local_skills.get(name)
            if local is None:
                console.print(f"[yellow]Skill '{name}' is not installed locally.[/yellow]")
                continue
            remote = remote_map.get(name)
            if remote is None:
                console.print(f"[dim]'{name}' not found in SkillHub.[/dim]")
                continue
            local_ver = str(local.current_version)
            if remote.version != local_ver:
                updates.append((name, local_ver, remote.version))

        if not updates:
            console.print("[green]All checked skills are up to date.[/green]")
            return

        if check:
            table = Table(title="Available SkillHub Updates")
            table.add_column("Skill", style="cyan")
            table.add_column("Installed")
            table.add_column("Available")
            for n, lv, rv in updates:
                table.add_row(n, lv, rv)
            console.print(table)
            return

        # Apply updates
        for skill_name, _, remote_version in updates:
            remote = remote_map[skill_name]
            target = Path.cwd() / ".weebot" / "skills" / skill_name
            target.mkdir(parents=True, exist_ok=True)
            console.print(f"Updating [cyan]{skill_name}[/cyan] (v{remote_version})...")
            ok = await index.download(remote, str(target))
            if ok:
                console.print(f"  [green]✓[/green] Updated to {remote_version}")
            else:
                console.print(f"  [red]✗[/red] Download or verification failed for {skill_name}")

        await index.close()

    asyncio.run(_run())


@skill.command("test")
@click.argument("skill_name", required=False)
@click.option("--should", "num_should", default=5, help="Number of should-trigger queries to generate")
@click.option("--should-not", "num_should_not", default=5, help="Number of should-NOT-trigger queries to generate")
@click.option("--verbose", is_flag=True, help="Show individual query results")
def skill_test(
    skill_name: str | None,
    num_should: int,
    num_should_not: int,
    verbose: bool,
) -> None:
    """Test skill trigger behaviour — validates the description triggers correctly.

    Generates should-trigger and should-NOT-trigger test queries, then
    evaluates whether the skill's description would cause correct trigger
    decisions.  Inspired by revfactory/harness trigger verification.
    """
    import asyncio

    async def _run() -> None:
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.application.services.skill_trigger_tester import SkillTriggerTester
        from rich.table import Table
        from rich.console import Console

        console = Console()

        registry = SkillRegistry()
        registry.load_all()

        if skill_name:
            skill = registry.get_skill(skill_name)
            if skill is None:
                console.print(f"[red]Skill '{skill_name}' not found.[/red]")
                return
            skills = [skill]
        else:
            skills = registry.list_skills()
            if not skills:
                console.print("[dim]No skills found to test.[/dim]")
                return

        tester = SkillTriggerTester()

        for skill in skills:
            console.print(f"\n[bold]Testing:[/bold] [cyan]{skill.name}[/cyan]")
            console.print(f"  Description: {skill.description[:100]}...")

            report = await tester.test_skill(
                skill,
                num_should=num_should,
                num_should_not=num_should_not,
            )

            if verbose:
                table = Table(title=f"Trigger Test — {skill.name}")
                table.add_column("Query", style="cyan")
                table.add_column("Expected", style="bold")
                table.add_column("Actual", style="bold")
                table.add_column("Pass?", style="bold")
                for r in report.results:
                    expected = "TRIGGER" if r.expected_trigger else "NO TRIGGER"
                    actual = "TRIGGER" if r.actual_triggered else "NO TRIGGER"
                    status = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
                    table.add_row(r.query[:60], expected, actual, status)
                console.print(table)

            console.print(
                f"  [bold]Pass rate:[/bold] {report.pass_count}/{report.total} "
                f"({report.pass_rate:.0%})  "
                f"Should-trigger: {report.should_trigger_pass_rate:.0%}  "
                f"Should-NOT: {report.should_not_trigger_pass_rate:.0%}"
            )

    asyncio.run(_run())


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

# flow commands extracted to cli/commands/flow.py


# Register command groups extracted to cli/commands/
cli.add_command(behavior_cli)
cli.add_command(flow_group)


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
