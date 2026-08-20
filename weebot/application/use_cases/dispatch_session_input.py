"""dispatch_session_input — single entry point for all user text sent to a session.

The web composer posts free text without knowing whether the session is
brand new, waiting for an answer, mid-execution, or finished — the four
existing verbs (start / resume / steer / chat) differ only in *what the
backend already knows about the session*, which is exactly what
``Session.status`` encodes. This module is a Strategy dispatch table
keyed by ``SessionStatus`` so the interface layer (the router) has one
endpoint to expose and the frontend has one call to make.

Each strategy is a thin orchestration function — the actual behavior
(TaskRunner background execution, event persistence, steering delivery)
is unchanged from the pre-existing dedicated endpoints; this module
only decides *which* of them applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

from weebot.domain.models.session import Session, SessionStatus

if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.application.ports.steering_port import SteeringPort
    from weebot.application.ports.task_runner_port import TaskRunnerPort


@dataclass
class SessionInputContext:
    """Everything a strategy needs, already resolved by the caller.

    Deliberately plain data + already-resolved collaborators rather than
    a container reference — keeps every strategy function unit-testable
    without a DI container or FastAPI request in scope.
    """

    session: Session
    text: str
    state_repo: StateRepositoryPort
    task_runner: TaskRunnerPort
    llm: LLMPort
    event_bus: EventBusPort
    steering: SteeringPort
    build_tools: Callable[[], Awaitable[object]]
    build_chat_flow: Callable[[Session, str | None], object]
    model: str | None = None
    client_msg_id: str | None = None
    ponytail_mode: str | None = None


@dataclass
class SessionInputResult:
    """What happened, for the response body."""

    session: Session
    verb: str  # "start" | "resume" | "steer" | "chat"


def _with_prompt(session: Session, text: str, model: str | None) -> Session:
    """Return a copy of *session* with ``context.last_prompt`` (and optionally
    ``context.model``) set — ``SessionContext`` is a typed Pydantic model, not
    a plain dict, so this goes through its own copy/``__setitem__`` rather
    than a ``{**session.context, ...}`` spread (which raises ``TypeError``:
    ``BaseModel`` doesn't support ``**`` unpacking without a ``keys()`` method).
    """
    new_context = session.context.model_copy(deep=True)
    new_context["last_prompt"] = text
    if model:
        new_context["model"] = model
    return session.model_copy(update={"context": new_context})


async def _start_task(ctx: SessionInputContext) -> SessionInputResult:
    """PENDING/FAILED → treat *text* as the task prompt and start PlanActFlow."""
    session = _with_prompt(ctx.session, ctx.text, ctx.model)
    await ctx.state_repo.save_session(session)

    tools = await ctx.build_tools()
    try:
        factory = ctx.task_runner.create_plan_act_factory(
            llm=ctx.llm,
            tools=tools,
            event_bus=ctx.event_bus,
            model=ctx.model,
            ponytail_mode=ctx.ponytail_mode,
            steering=ctx.steering,
        )
        session = await ctx.task_runner.start_session(session, factory)
    except Exception:
        await tools.teardown()
        raise
    return SessionInputResult(session=session, verb="start")


async def _resume(ctx: SessionInputContext) -> SessionInputResult:
    """WAITING → answer the pending question and resume PlanActFlow."""
    from weebot.domain.models.event import MessageEvent

    session = ctx.session.add_event(MessageEvent(role="user", message=ctx.text))
    session = session.set_status(SessionStatus.RUNNING)
    await ctx.state_repo.save_session(session)
    return SessionInputResult(session=session, verb="resume")


async def _steer(ctx: SessionInputContext) -> SessionInputResult:
    """RUNNING → non-blocking mid-execution feedback, observed at next step boundary."""
    await ctx.steering.send(ctx.session.id, ctx.text)
    return SessionInputResult(session=ctx.session, verb="steer")


async def _chat(ctx: SessionInputContext) -> SessionInputResult:
    """COMPLETED (or any status without a dedicated strategy) → a new chat turn.

    Runs via TaskRunner exactly like ``_start_task`` — ``TaskRunner.start_session``
    is flow-agnostic (it only calls ``flow.run(session.context["last_prompt"])``),
    so a ChatFlow factory works the same way a PlanActFlow factory does.
    """
    session = _with_prompt(ctx.session, ctx.text, ctx.model)
    await ctx.state_repo.save_session(session)

    def _factory(s: Session):
        return ctx.build_chat_flow(s, ctx.model)

    session = await ctx.task_runner.start_session(session, _factory)
    return SessionInputResult(session=session, verb="chat")


_STRATEGIES: dict[SessionStatus, Callable[[SessionInputContext], Awaitable[SessionInputResult]]] = {
    SessionStatus.PENDING: _start_task,
    SessionStatus.FAILED: _start_task,
    SessionStatus.WAITING: _resume,
    SessionStatus.RUNNING: _steer,
    SessionStatus.COMPLETED: _chat,
}


async def dispatch_session_input(ctx: SessionInputContext) -> SessionInputResult:
    """Route *ctx* to the strategy matching ``ctx.session.status``."""
    strategy = _STRATEGIES.get(ctx.session.status)
    if strategy is None:
        raise ValueError(f"No input strategy registered for session status {ctx.session.status!r}")
    return await strategy(ctx)
