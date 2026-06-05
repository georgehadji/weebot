import asyncio
from pathlib import Path

import click
from rich.console import Console

console = Console()

@click.group()
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


@click.group()
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


