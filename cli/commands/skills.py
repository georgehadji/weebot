"""Skill CLI commands — convert, list, install, update, test."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)


def _rebuild_bm25_index(rebuild_console: Console) -> None:
    """Rebuild the BM25 skill index from the current registry.

    Called after install/update so newly added skills are immediately
    retrievable by the executor without a process restart.

    Non-fatal: any error is logged and swallowed so the CLI command
    still exits 0.
    """
    try:
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.application.services.bm25_skill_retriever import BM25SkillRetriever

        registry = SkillRegistry()
        registry.load_all()
        skills = registry.list_skills()
        retriever = BM25SkillRetriever(registry)  # refresh() is called in __init__
        has_bm25 = getattr(retriever, '_bm25', None) is not None
        engine = "BM25" if has_bm25 else "word-overlap"
        rebuild_console.print(f"  [dim]{engine} index rebuilt ({len(skills)} skills)[/dim]")
    except Exception as exc:
        logger.warning("BM25 rebuild skipped: %s", exc)


@click.group()
def skill() -> None:
    """Manage and convert skills."""
    pass


@skill.command("convert")
@click.argument("source", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override skill name")
@click.option("--output", default=None, help="Target directory (default: skills/builtin/<name>)")
def skill_convert(source: str, name: str | None, output: str | None) -> None:
    """Convert an external skill to Weebot format."""
    async def _run():
        from weebot.application.skills.skill_converter import SkillConverter
        report = SkillConverter().convert(Path(source))
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
    async def _run():
        from weebot.application.skills.format_detector import FormatDetector
        from weebot.application.skills.skill_converter import SkillConverter
        from weebot.domain.models.skill_source import SourceFormat
        import_dir = Path("skills/import")
        if not import_dir.exists():
            console.print("[yellow]No skills/import/ directory found[/yellow]")
            return
        converter = SkillConverter(); found = 0; converted = 0
        for entry in sorted(import_dir.iterdir()):
            source = FormatDetector.detect(entry)
            if source.format not in (SourceFormat.UNKNOWN, SourceFormat.WEEBOT):
                found += 1
                if dry_run:
                    console.print(f"  [blue]Would convert:[/blue] {entry.name} ({source.format.value})")
                else:
                    report = converter.convert(entry)
                    if report.success:
                        converted += 1; console.print(f"  [green]✓ {entry.name}[/green]")
                    else:
                        console.print(f"  [red]✗ {entry.name}: {report.errors[0]}[/red]")
        if found == 0:
            console.print("[yellow]No external skills found[/yellow]")
        else:
            console.print(f"\nFound: {found}, Converted: {converted}")
    asyncio.run(_run())


@skill.command("list")
@click.option("--active-only", is_flag=True, help="Show only active skills")
def skill_list(active_only: bool) -> None:
    """List all discovered skills."""
    async def _run():
        from weebot.application.skills.skill_registry import SkillRegistry
        registry = SkillRegistry(); registry.load_all()
        skills = registry.get_active_skills() if active_only else registry.list_skills()
        if not skills:
            console.print("[dim]No skills found.[/dim]"); return
        table = Table(title="Installed Skills")
        table.add_column("Name", style="cyan"); table.add_column("Description"); table.add_column("Source", style="dim")
        for sk in sorted(skills, key=lambda s: s.name):
            table.add_row(sk.name, sk.description[:80], sk.source_path or "—")
        console.print(table)
    asyncio.run(_run())


@skill.command("install")
@click.argument("source", type=click.Path(exists=True))
@click.option("--name", default=None, help="Override skill name")
def skill_install(source: str, name: str | None) -> None:
    """Install a skill from a file or directory."""
    async def _run():
        import yaml
        from weebot.application.skills.format_detector import FormatDetector
        from weebot.application.skills.skill_converter import SkillConverter
        from weebot.domain.models.skill_source import SourceFormat
        src = Path(source).resolve()
        detected = FormatDetector.detect(src)
        skill_name = name or detected.name or src.stem
        target = Path.cwd() / ".weebot" / "skills" / skill_name
        if detected.format in (SourceFormat.WEEBOT, SourceFormat.MANUS):
            skill_md = src if src.is_file() and src.name == "SKILL.md" else src / "SKILL.md"
            if not skill_md.exists() or skill_md.name != "SKILL.md":
                console.print(f"[red]✗[/red] Expected SKILL.md at {source}"); return
            if not skill_md.read_bytes()[:200].startswith(b"---"):
                console.print(f"[red]✗[/red] Missing YAML frontmatter"); return
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(skill_md), str(target / "SKILL.md"))
            console.print(f"[green]✓[/green] Installed '[cyan]{skill_name}[/cyan]'")
            _rebuild_bm25_index(console)
            return
        if detected.format in (SourceFormat.MYMANUS, SourceFormat.AGENTICSEEK):
            report = SkillConverter(skills_dir=target.parent).convert(src)
            if report.success:
                console.print(f"[green]✓[/green] Installed '[cyan]{skill_name}[/cyan]'")
            else:
                console.print(f"[red]✗[/red] Conversion failed: {report.errors[0]}")
            return
        console.print(f"[red]✗[/red] Cannot determine format of {source}")
    asyncio.run(_run())


@skill.command("update")
@click.argument("skill_name", required=False)
@click.option("--check", is_flag=True, help="Check for updates without installing")
@click.option("--source", type=click.Choice(["skillhub", "agentskills"]), default="skillhub")
def skill_update(skill_name: str | None, check: bool, source: str) -> None:
    """Update installed skills from the SkillHub remote index."""
    async def _run():
        from weebot.application.skills.skill_registry import SkillRegistry
        registry = SkillRegistry(); registry.load_all()
        local = {s.name: s for s in registry.list_skills()}
        if not local:
            console.print("[dim]No local skills found.[/dim]"); return

        if source == "agentskills":
            from weebot.infrastructure.adapters.awesome_agent_skills_adapter import (
                AwesomeAgentSkillsAdapter,
            )
            index = AwesomeAgentSkillsAdapter()
        else:
            from weebot.infrastructure.adapters.skill_index_github import GitHubSkillIndexAdapter
            index = GitHubSkillIndexAdapter()

        remote = await index.fetch_index()
        remote_map = {s.name: s for s in remote}
        if not remote_map:
            console.print("[yellow]Could not fetch remote skill index.[/yellow]"); return
        names = [skill_name] if skill_name else list(local.keys())
        updates = [(n, str(local[n].current_version), remote_map[n].version)
                   for n in names if n in local and n in remote_map
                   and remote_map[n].version != str(local[n].current_version)]
        if not updates:
            console.print("[green]All skills up to date.[/green]"); return
        if check:
            t = Table(title="Available Updates")
            t.add_column("Skill", style="cyan"); t.add_column("Installed"); t.add_column("Available")
            for n, lv, rv in updates: t.add_row(n, lv, rv)
            console.print(t); return
        for sn, _, rv in updates:
            r = remote_map[sn]
            tgt = Path.cwd() / ".weebot" / "skills" / sn; tgt.mkdir(parents=True, exist_ok=True)
            console.print(f"Updating [cyan]{sn}[/cyan] (v{rv})...")
            ok = await index.download(r, str(tgt))
            console.print(f"  {'[green]✓[/green]' if ok else '[red]✗[/red]'} Updated" if ok else f"  [red]✗[/red] Failed")
        await index.close()
        _rebuild_bm25_index(console)
    asyncio.run(_run())


@skill.command("test")
@click.argument("skill_name", required=False)
@click.option("--should", "num_should", default=5)
@click.option("--should-not", "num_should_not", default=5)
@click.option("--verbose", is_flag=True)
def skill_test(skill_name: str | None, num_should: int, num_should_not: int, verbose: bool) -> None:
    """Test skill trigger behaviour."""
    async def _run():
        from weebot.application.skills.skill_registry import SkillRegistry
        from weebot.application.services.skill_trigger_tester import SkillTriggerTester
        registry = SkillRegistry(); registry.load_all()
        skills = [registry.get_skill(skill_name)] if skill_name else registry.list_skills()
        skills = [s for s in skills if s]
        if not skills:
            console.print("[dim]No skills found.[/dim]"); return
        tester = SkillTriggerTester()
        for skill in skills:
            console.print(f"\n[bold]Testing:[/bold] [cyan]{skill.name}[/cyan]")
            report = await tester.test_skill(skill, num_should=num_should, num_should_not=num_should_not)
            if verbose:
                t = Table(title=f"Trigger Test — {skill.name}")
                t.add_column("Query", style="cyan"); t.add_column("Expected", style="bold")
                t.add_column("Actual", style="bold"); t.add_column("Pass?", style="bold")
                for r in report.results:
                    expected = "TRIGGER" if r.expected_trigger else "NO TRIGGER"
                    actual = "TRIGGER" if r.actual_triggered else "NO TRIGGER"
                    t.add_row(r.query[:60], expected, actual, "[green]✓[/green]" if r.passed else "[red]✗[/red]")
                console.print(t)
            console.print(f"  [bold]Pass rate:[/bold] {report.pass_count}/{report.total} ({report.pass_rate:.0%})")
    asyncio.run(_run())
