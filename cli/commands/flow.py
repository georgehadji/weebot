"""Flow CLI commands — PlanActFlow orchestration (new architecture)."""

from __future__ import annotations

import asyncio
import uuid

import click
from rich.console import Console
from rich.table import Table

from weebot.application.di import Container
from weebot.application.cqrs.mediator import Mediator
from weebot.application.ports.event_bus_port import EventBusPort
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.config.model_refs import MODEL_COMMAND_DEFAULT
from weebot.domain.models.event import WaitForUserEvent
from weebot.interfaces.cli.agent_runner import AgentRunner
from weebot.interfaces.cli.event_logger import CLIEventSubscriber

console = Console()

# Shared container — initialized lazily
_container: Container | None = None


def _run_async(coro_factory) -> None:
    """Run an async CLI command body, draining background work and DB pools.

    aiosqlite worker threads are non-daemon, so a connection pool left open
    keeps the interpreter alive at shutdown — Python joins those threads and
    hangs forever. Closing pools inside the same event loop (on both success
    and failure paths) ensures the process always exits cleanly, even when a
    query raises (e.g. a corrupt database).

    Background tasks are drained first, for the opposite reason: asyncio.run()
    cancels whatever is still pending when the body returns, so without a
    bounded wait here the post-completion work is started and then killed.
    """

    async def _wrapper() -> None:
        import sys

        if sys.stdin.isatty():
            # ADR-013: a person at a terminal answers tool-call approvals here.
            from weebot.application.ports.event_store_port import EventStorePort
            from weebot.application.services.tool_approval import (
                ConsoleApproval,
                set_approval_journal,
                set_process_approval,
            )

            set_process_approval(ConsoleApproval())
            _get_state_repo()  # builds the shared container
            set_approval_journal(_container.get(EventStorePort))
        try:
            await coro_factory()
        finally:
            from weebot.application.services.background_tasks import get_background_tasks
            from weebot.infrastructure.persistence.connection_pool import close_all_pools

            # Before the pools, because the post-completion work (retention
            # review, skill-gap processing, the dream scan) reads the database.
            # Without this drain those tasks did not merely go unowned — they
            # were cancelled outright when asyncio.run() returned, so the CLI
            # paid to build a Container and start LLM adapters for work that
            # never finished. Bounded, so a slow background job delays exit but
            # cannot prevent it.
            await get_background_tasks().drain()
            from weebot.interfaces.factories import close_mcp_toolkit

            await close_mcp_toolkit()
            await close_all_pools()

    asyncio.run(_wrapper())


def _get_container() -> Container:
    """The process's one container, built on first use."""
    global _container
    if _container is None:
        from weebot.interfaces.factories import shared_container

        _container = shared_container()
    return _container


def _cli_llm(model_id: str):
    """The CLI's ``LLMPort``: built by the container, so bounded by the global pool.

    These commands used to call ``ModelSelectionService.create_llm_adapter``, which
    constructed an adapter outside the container and returned it unwrapped. Two
    executor call sites bypass the cascade's own slot (``_tool_executor.py:587``,
    ``_context_compressor.py:246``), so with that adapter in hand they were neither
    timed nor counted by ``LLMPool`` (WB-02).
    """
    return _get_container().create_llm_for_model(model_id)


def _get_state_repo() -> StateRepositoryPort:
    return _get_container().get(StateRepositoryPort)


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

        llm = _cli_llm(model or MODEL_BUDGET)
        state_repo = _get_state_repo()
        mediator = _get_mediator()
        run_session_id = session_id or str(uuid.uuid4())
        runner = AgentRunner(
            llm=llm,
            state_repo=state_repo,
            mediator=mediator,
            model=model,
            use_rich=False,
            retention_agent=_container.get("retention_agent"),
            # Domain events and the skill-gap subscription need the bus (F56).
            event_bus=_container.get(EventBusPort),
        )
        try:
            subscriber = CLIEventSubscriber(use_rich=True)

            waiting = False
            async for event in runner.run_prompt(prompt, session_id=run_session_id):
                await subscriber.on_event(event)
                if isinstance(event, WaitForUserEvent):
                    waiting = True
                    break
            # Every question on the way gets asked: plan review, then e.g. the
            # constraint gate. Answering only the first one ended the command with
            # the session still waiting and nothing said.
            while waiting:
                # to_thread: a bare input() here would block the event loop,
                # freezing the runner's own background tasks while it waits.
                # The subscriber above already printed the question (F37).
                try:
                    answer = await asyncio.to_thread(input, "\nYour answer: ")
                except EOFError:
                    # stdin closed (a script, CI, a pipe): never answer for the
                    # user. The session stays WAITING and can be resumed.
                    click.echo(
                        f"\nNo answer on stdin; session {run_session_id} is waiting. "
                        "Resume it with: python -m cli.main flow resume "
                        f'{run_session_id} "<answer>"'
                    )
                    break
                waiting = False
                async for resume_event in runner.resume_session(run_session_id, answer):
                    await subscriber.on_event(resume_event)
                    if isinstance(resume_event, WaitForUserEvent):
                        waiting = True
                        break

        finally:
            await runner.close()  # tools: Apify HTTP sessions, the browser

    _run_async(_run)


@flow.command("resume")
@click.argument("session_id")
@click.argument("answer")
def flow_resume(session_id: str, answer: str) -> None:
    """Resume a waiting session with a user answer."""

    async def _run() -> None:
        from weebot.config.model_refs import MODEL_BUDGET

        llm = _cli_llm(MODEL_BUDGET)
        state_repo = _get_state_repo()
        mediator = _get_mediator()
        runner = AgentRunner(
            llm=llm,
            state_repo=state_repo,
            mediator=mediator,
            use_rich=False,
            event_bus=_container.get(EventBusPort),
        )
        try:
            subscriber = CLIEventSubscriber(use_rich=True)

            async for event in runner.resume_session(session_id, answer):
                await subscriber.on_event(event)

        finally:
            await runner.close()  # tools: Apify HTTP sessions, the browser

    _run_async(_run)


def _checkpoint_store():
    from weebot.application.ports.checkpoint_port import CheckpointPort

    return _get_container().get(CheckpointPort)


async def _resume_inline(session_id: str, answer: str):
    """Run a WAITING session inline, as `flow resume` does, yielding its events."""
    from weebot.config.model_refs import MODEL_BUDGET

    runner = AgentRunner(
        llm=_cli_llm(MODEL_BUDGET),
        state_repo=_get_state_repo(),
        mediator=_get_mediator(),
        use_rich=False,
        event_bus=_get_container().get(EventBusPort),
    )
    try:
        async for event in runner.resume_session(session_id, answer):
            yield event
    finally:
        await runner.close()


@flow.command("recover")
@click.argument("session_id")
def flow_recover(session_id: str) -> None:
    """Resume an interrupted session from its last checkpoint (WEEBOT_FLOW_CHECKPOINTS)."""
    from weebot.application.flows._checkpoint_scheduler import restore_from_checkpoint

    async def _run() -> None:
        repo = _get_state_repo()
        session = await repo.load_session(session_id)
        if session is None:
            raise click.ClickException(f"session {session_id} not found")
        checkpoint = await _checkpoint_store().load(session_id)
        if checkpoint is None:
            raise click.ClickException(
                f"session {session_id} has no checkpoint (is WEEBOT_FLOW_CHECKPOINTS on?)"
            )
        await repo.save_session(restore_from_checkpoint(session, checkpoint))
        subscriber = CLIEventSubscriber(use_rich=True)
        async for event in _resume_inline(session_id, "Continue from the last checkpoint."):
            await subscriber.on_event(event)

    _run_async(_run)


@flow.command("list")
@click.option("--user-id", default=None, help="Filter by user ID")
def flow_list(user_id: str | None) -> None:
    """List active/waiting sessions."""

    async def _run() -> None:
        from weebot.config.model_refs import MODEL_BUDGET

        llm = _cli_llm(MODEL_BUDGET)
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

        llm = _cli_llm(MODEL_BUDGET)
        state_repo = _get_state_repo()
        runner = AgentRunner(llm=llm, state_repo=state_repo)
        if await runner.cancel_session(session_id):
            console.print(f"[green]Cancelled session {session_id}[/green]")
            return
        # Another process may be running it (F77): file a request it checks
        # every iteration; a session nobody is running is marked failed here.
        from weebot.core import cancel_requests
        from weebot.domain.models.session import SessionStatus

        session = await state_repo.load_session(session_id)
        if session is None:
            console.print(f"[yellow]Session {session_id} not found[/yellow]")
        elif session.status in (
            SessionStatus.RUNNING, SessionStatus.WAITING, SessionStatus.PENDING
        ):
            # A resumed run keeps WAITING in the store while it works, so file the
            # request for every open status; mark it failed too in case nothing runs it.
            cancel_requests.request(session_id)
            if session.status != SessionStatus.RUNNING:
                await state_repo.update_session_status(session_id, SessionStatus.FAILED)
            console.print(
                f"[green]Cancel requested for {session_id}; a process running it stops "
                f"at its next step.[/green]"
            )
        else:
            console.print(
                f"[yellow]Session {session_id} is {session.status.value}; nothing to cancel"
                f"[/yellow]"
            )

    _run_async(_run)


@flow.command("retry")
@click.argument("session_id")
def flow_retry(session_id: str) -> None:
    """Retry a failed session (dead-letter queue).

    Re-enters the session at the last saved state with a full retry budget.
    Only works for sessions in FAILED status.
    """

    async def _run() -> None:
        global _container
        if _container is None:
            from weebot.interfaces.factories import shared_container

            _container = shared_container()
        from weebot.application.services.task_runner import TaskRunner

        runner = _container.get(TaskRunner)
        ok = await runner.rerun_failed_session(session_id)
        if ok:
            console.print(f"[green]Retrying failed session {session_id}[/green]")
        else:
            console.print(
                f"[yellow]Session {session_id} is not FAILED, or was not run by this "
                f"process: retry works only in the process that ran it (the web "
                f"server). From the CLI, start it again with 'flow run'.[/yellow]"
            )

    _run_async(_run)


@flow.command("undo")
@click.argument("session_id")
def flow_undo(session_id: str) -> None:
    """Undo the last plan mutation for a session."""

    async def _run() -> None:
        llm = _cli_llm(MODEL_COMMAND_DEFAULT)
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
@click.option(
    "--planning/--no-planning", default=False, help="Enable SIA-inspired pre-reflect planning"
)
def flow_skillopt(
    skill_name: str, epochs: int, steps: int, batch: int, output: str, planning: bool
) -> None:
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
                    f"    [red]✗ rejected[/red]  " f"{e.skill_name}  drop={e.score_drop:.3f}"
                )
            elif event_type == "done":
                console.print(f"\n[bold green]SkillOpt complete → {output}[/bold green]")
            else:
                console.print(f"  [{event_type}]")

    _run_async(_run)


@flow.command("export")
@click.argument("session_id")
@click.option(
    "--output", default=None, help="Output .jsonl file path (default: <session_id>.jsonl)"
)
@click.option(
    "--compress",
    default=None,
    type=int,
    help="Compress middle turns to fit this token budget before export",
)
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

        decisions = [e for e in session.events if getattr(e, "type", "") == "product_decision"]

        if not decisions:
            console.print("[dim]No product decisions logged for this session.[/dim]")
            return

        for d in decisions:
            stamp = d.timestamp.isoformat()[:10] if hasattr(d, "timestamp") else "N/A"
            door = "🔴 One-way door" if d.reversibility == "one-way" else "🟢 Two-way door"
            console.print(
                Panel.fit(
                    f"[bold]Decision:[/bold] {d.title}\n"
                    f"[bold]Date:[/bold] {stamp}\n"
                    f"[bold]Problem:[/bold] {d.problem[:200]}\n"
                    f"[bold]Why now:[/bold] {d.why_now[:200]}\n"
                    f"[bold]Choice:[/bold] {d.choice[:200]}\n"
                    f"[bold]Reversibility:[/bold] {door}\n"
                    f"[bold]Success metric:[/bold] {d.success_metric[:200]}\n"
                    + (
                        f"[bold]Revisit trigger:[/bold] {d.revisit_trigger[:200]}\n"
                        if d.revisit_trigger
                        else ""
                    )
                    + (
                        f"[bold]Options considered:[/bold] {', '.join(d.options_considered[:5])}\n"
                        if d.options_considered
                        else ""
                    )
                    + f"[bold]Session:[/bold] {d.session_id[:20]}",
                    title="📋 Product Decision",
                    border_style="blue",
                )
            )

        console.print(f"\n[dim]{len(decisions)} decision(s) found[/dim]")

    _run_async(_run)
