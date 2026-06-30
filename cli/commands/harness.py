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


@harness.command("evolve")
@click.option("--harness-path", default="weebot/config/harness/v0.2.0.yaml",
              show_default=True, help="Base harness YAML path")
@click.option("--output-dir", default=None,
              help="Output directory for evolved harnesses (default: <harness_path>/evolved/)")
@click.option("--held-in-tasks", "-i", multiple=True,
              help="Task IDs for held-in evaluation (repeatable)")
@click.option("--held-out-tasks", "-o", multiple=True,
              help="Task IDs for held-out evaluation (repeatable)")
@click.option("--max-proposals", default=3, type=int, show_default=True)
@click.option("--iterations", default=1, type=int, show_default=True,
              help="Number of Self-Harness optimization iterations")
@click.option("--db", default="./weebot_sessions.db", show_default=True)
def harness_evolve(
    harness_path: str, output_dir: str | None,
    held_in_tasks: tuple[str, ...], held_out_tasks: tuple[str, ...],
    max_proposals: int, iterations: int, db: str,
) -> None:
    """Run the Self-Harness optimization loop to evolve an agent harness.

    The harness is evaluated against held-in tasks, failure patterns
    are mined from the trajectory repository, and the LLM proposes
    targeted instruction edits.  Edits that pass regression testing
    (Δ_in ≥ 0, Δ_ho ≥ 0) are promoted to new versioned YAML files.
    """
    import asyncio
    from pathlib import Path

    async def _run() -> None:
        from weebot.application.di import Container
        from weebot.application.flows.harness_opt_flow import HarnessOptFlow
        from weebot.application.services.harness_optimization_target import (
            HarnessOptimizationTarget,
        )
        from weebot.application.ports.llm_port import LLMPort
        from weebot.infrastructure.persistence.trajectory_repo import (
            TrajectoryRepository,
        )

        console.print(f"[bold]Self-Harness Evolution[/bold]")
        console.print(f"  Harness: {harness_path}")
        console.print(f"  Held-in tasks: {list(held_in_tasks)}")
        console.print(f"  Held-out tasks: {list(held_out_tasks)}")
        console.print(f"  Max proposals per iteration: {max_proposals}")
        console.print(f"  Iterations: {iterations}")

        # Bootstrap DI container
        container = Container()
        container.configure_defaults(db_path=db)
        llm = container.get(LLMPort)
        trajectory_repo = TrajectoryRepository(db_path=db)

        # Create optimization target
        target = HarnessOptimizationTarget(
            harness_path=harness_path,
            output_dir=output_dir,
        )
        await target.load()

        if not held_in_tasks and not held_out_tasks:
            console.print("[yellow]No held-in or held-out tasks provided — "
                          "the optimizer can mine existing failure patterns "
                          "but cannot validate proposals.[/yellow]")

        for iteration in range(iterations):
            console.print(f"\n[bold]Iteration {iteration + 1}/{iterations}[/bold]")

            flow = HarnessOptFlow(
                llm=llm,
                target=target,
                trajectory_repo=trajectory_repo,
                held_in_tasks=list(held_in_tasks),
                held_out_tasks=list(held_out_tasks),
                max_proposals=max_proposals,
            )

            try:
                async for event in flow.run():
                    if hasattr(event, "message") and event.message:
                        console.print(f"  {event.message}")
            except Exception as exc:
                console.print(f"[red]Iteration failed: {exc}[/red]")
                break

            if flow.is_done():
                console.print(f"[green]✓ Iteration {iteration + 1} complete[/green]")

        await trajectory_repo.close()
        console.print("\n[bold green]Self-Harness evolution complete.[/bold green]")

    asyncio.run(_run())


