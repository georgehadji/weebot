"""Flow CLI commands — PlanActFlow orchestration (new architecture)."""
from __future__ import annotations

import asyncio
import uuid

import click
from rich.console import Console
from rich.table import Table

from weebot.application.di import Container
from weebot.application.cqrs.mediator import Mediator
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.model_selection import ModelSelectionService
from weebot.config.model_refs import MODEL_COMMAND_DEFAULT
from weebot.domain.models.event import WaitForUserEvent
from weebot.interfaces.cli.agent_runner import AgentRunner
from weebot.interfaces.cli.event_logger import CLIEventSubscriber

console = Console()

# Shared container — initialized lazily
_container: Container | None = None


def _run_async(coro_factory) -> None:
    """Run an async CLI command body, guaranteeing DB pool teardown.

    aiosqlite worker threads are non-daemon, so a connection pool left open
    keeps the interpreter alive at shutdown — Python joins those threads and
    hangs forever. Closing pools inside the same event loop (on both success
    and failure paths) ensures the process always exits cleanly, even when a
    query raises (e.g. a corrupt database).
    """
    async def _wrapper() -> None:
        try:
            await coro_factory()
        finally:
            from weebot.infrastructure.persistence.connection_pool import (
                close_all_pools,
            )
            await close_all_pools()

    asyncio.run(_wrapper())


def _get_state_repo() -> StateRepositoryPort:
    global _container
    if _container is None:
        _container = Container()
        _container.configure_defaults()
    return _container.get(StateRepositoryPort)


def _get_mediator():
    """Return the shared CQRS Mediator (requires _get_state_repo called first)."""
    global _container
    assert _container is not None, "Container must be initialized — call _get_state_repo() first"
    return _container.get(Mediator)


@click.group()
def flow() -> None:
    """PlanActFlow commands (new architecture)."""
    pass


@flow.command("run")
@click.argument("prompt")
@click.option("--session-id", default=None, help="Session identifier")
@click.option("--model", default=None, help="Override default LLM model")
def flow_run(prompt: str, session_id: str | None, model: str | None) -> None:
    """Run a one-shot PlanActFlow with the given prompt."""
    async def _run() -> None:
        from weebot.config.model_refs import MODEL_BUDGET
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter(model or MODEL_BUDGET)
        state_repo = _get_state_repo()
        mediator = _get_mediator()
        run_session_id = session_id or str(uuid.uuid4())
        runner = AgentRunner(llm=llm, state_repo=state_repo, mediator=mediator, model=model, use_rich=False)
        subscriber = CLIEventSubscriber(use_rich=True)

        async for event in runner.run_prompt(prompt, session_id=run_session_id):
            await subscriber.on_event(event)
            if isinstance(event, WaitForUserEvent):
                answer = input(f"\n[weebot asks] {event.question}\nYour answer: ")
                async for resume_event in runner.resume_session(run_session_id, answer):
                    await subscriber.on_event(resume_event)
                break

    _run_async(_run)


@flow.command("resume")
@click.argument("session_id")
@click.argument("answer")
def flow_resume(session_id: str, answer: str) -> None:
    """Resume a waiting session with a user answer."""
    async def _run() -> None:
        from weebot.config.model_refs import MODEL_BUDGET
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter(MODEL_BUDGET)
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo, use_rich=False)
        subscriber = CLIEventSubscriber(use_rich=True)

        async for event in runner.resume_session(session_id, answer):
            await subscriber.on_event(event)

    _run_async(_run)


@flow.command("list")
@click.option("--user-id", default=None, help="Filter by user ID")
def flow_list(user_id: str | None) -> None:
    """List active/waiting sessions."""
    async def _run() -> None:
        from weebot.config.model_refs import MODEL_BUDGET
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter(MODEL_BUDGET)
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

    _run_async(_run)


@flow.command("cancel")
@click.argument("session_id")
def flow_cancel(session_id: str) -> None:
    """Cancel a running session."""
    async def _run() -> None:
        from weebot.config.model_refs import MODEL_BUDGET
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter(MODEL_BUDGET)
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo)
        ok = await runner.cancel_session(session_id)
        if ok:
            console.print(f"[green]Cancelled session {session_id}[/green]")
        else:
            console.print(f"[yellow]Session {session_id} was not active[/yellow]")

    _run_async(_run)


@flow.command("undo")
@click.argument("session_id")
def flow_undo(session_id: str) -> None:
    """Undo the last plan mutation for a session."""
    async def _run() -> None:
        model_service = ModelSelectionService()
        llm = model_service.create_llm_adapter(MODEL_COMMAND_DEFAULT)
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo)
        ok = await runner.flow_undo(session_id)
        if ok:
            console.print(f"[green]Undid last plan change for session {session_id}[/green]")
        else:
            console.print(f"[yellow]Nothing to undo for session {session_id}[/yellow]")

    _run_async(_run)


@flow.command("skillopt")
@click.argument("skill_name")
@click.option("--epochs", default=4, help="Number of optimization epochs")
@click.option("--steps", default=5, help="Steps per epoch")
@click.option("--batch", default=40, help="Batch size")
@click.option("--output", default="best_skill.md", help="Output skill file path")
@click.option("--planning/--no-planning", default=False, help="Enable SIA-inspired pre-reflect planning")
def flow_skillopt(skill_name: str, epochs: int, steps: int, batch: int, output: str, planning: bool) -> None:
    """Run SkillOptFlow — optimize a skill through rollout → reflect → merge → validate."""
    async def _run() -> None:
        container = Container()
        container.configure_defaults()
        container.configure_skillopt()

        flow = container.build_skill_opt_flow(
            skill_name=skill_name,
            train_tasks=[],
            validation_tasks=None,
            output_path=output,
            epochs=epochs,
            steps_per_epoch=steps,
            batch_size=batch,
            use_planning=planning,
        )

        console.print(f"[bold]SkillOptFlow: {skill_name}[/bold]")
        console.print(f"  Epochs: {epochs}  Steps/epoch: {steps}  Batch: {batch}")
        console.print(f"  Planning: {planning}  Output: {output}\n")

        async for event in flow.run():
            event_type = getattr(event, "type", "?")
            if event_type == "epoch_completed":
                e = event
                console.print(
                    f"  [green]Epoch {e.epoch}[/green]  "
                    f"best_score={e.best_validation_score:.3f}  "
                    f"accepted={e.edits_accepted}  rejected={e.edits_rejected}"
                )
            elif event_type == "skill_edit_accepted":
                e = event
                console.print(
                    f"    [green]✓ accepted[/green]  "
                    f"{e.skill_name} v{e.old_version}→v{e.new_version}  "
                    f"Δ={e.validation_score_delta:+.3f}"
                )
            elif event_type == "skill_edit_rejected":
                e = event
                console.print(
                    f"    [red]✗ rejected[/red]  "
                    f"{e.skill_name}  drop={e.score_drop:.3f}"
                )
            elif event_type == "done":
                console.print(f"\n[bold green]SkillOpt complete → {output}[/bold green]")
            else:
                console.print(f"  [{event_type}]")

    _run_async(_run)


@flow.command("export")
@click.argument("session_id")
@click.option("--output", default=None, help="Output .jsonl file path (default: <session_id>.jsonl)")
@click.option("--compress", default=None, type=int, help="Compress middle turns to fit this token budget before export")
def flow_export(session_id: str, output: str | None, compress: int | None) -> None:
    """Export session events to JSONL for analysis or fine-tuning."""
    from weebot.application.services.trajectory_exporter import TrajectoryExporter

    dest = output or f"{session_id}.jsonl"

    async def _run() -> None:
        state_repo = _get_state_repo()
        exporter = TrajectoryExporter(repo=state_repo)
        count = await exporter.export_session(session_id, str(dest), compress=compress)
        console.print(f"[green]✓[/green] Exported {count} events to {dest}")

    _run_async(_run)


@flow.command("search")
@click.argument("query")
@click.option("--limit", default=10, type=int, help="Max results")
def cmd_flow_search(query: str, limit: int) -> None:
    """Full-text search with goal→match→resolution bookends."""
    async def _run() -> None:
        state_repo = _get_state_repo()
        from weebot.application.services.session_search_service import SessionSearchService
        svc = SessionSearchService(state_repo=state_repo)
        results = await svc.search(query, limit=limit)

        if not results:
            console.print("[dim]No results found.[/dim]")
            return

        table = Table(title=f"Session Search: {query}")
        table.add_column("Session ID", style="cyan", no_wrap=True)
        table.add_column("Goal", style="yellow")
        table.add_column("Resolution", style="green")
        table.add_column("Match", style="white")
        table.add_column("Score", justify="right")

        for r in results:
            table.add_row(
                r.session_id[:12] + "...",
                r.goal[:60],
                r.resolution[:60],
                r.match_summary[:60],
                f"{r.score:.3f}",
            )
        console.print(table)

    _run_async(_run)


@flow.command("decisions")
@click.argument("session_id")
def cmd_flow_decisions(session_id: str) -> None:
    """List product decisions logged for a session."""
    async def _run() -> None:
        from rich.panel import Panel

        state_repo = _get_state_repo()
        session = await state_repo.load_session(session_id)

        if session is None:
            console.print(f"[red]✗[/red] Session not found: {session_id}")
            return

        decisions = [
            e for e in session.events
            if getattr(e, "type", "") == "product_decision"
        ]

        if not decisions:
            console.print("[dim]No product decisions logged for this session.[/dim]")
            return

        for d in decisions:
            console.print(Panel.fit(
                f"[bold]Decision:[/bold] {d.title}\n"
                f"[bold]Date:[/bold] {d.timestamp.isoformat()[:10] if hasattr(d, 'timestamp') else 'N/A'}\n"
                f"[bold]Problem:[/bold] {d.problem[:200]}\n"
                f"[bold]Why now:[/bold] {d.why_now[:200]}\n"
                f"[bold]Choice:[/bold] {d.choice[:200]}\n"
                f"[bold]Reversibility:[/bold] {'🔴 One-way door' if d.reversibility == 'one-way' else '🟢 Two-way door'}\n"
                f"[bold]Success metric:[/bold] {d.success_metric[:200]}\n"
                + (f"[bold]Revisit trigger:[/bold] {d.revisit_trigger[:200]}\n" if d.revisit_trigger else "")
                + (f"[bold]Options considered:[/bold] {', '.join(d.options_considered[:5])}\n" if d.options_considered else "")
                + f"[bold]Session:[/bold] {d.session_id[:20]}",
                title="📋 Product Decision",
                border_style="blue",
            ))

        console.print(f"\n[dim]{len(decisions)} decision(s) found[/dim]")

    _run_async(_run)
