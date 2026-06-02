"""Command and Query handlers for Weebot operations.

Each handler enforces business rules and delegates to domain/application
services.  Handlers are registered with the Mediator, which runs them
through pipeline behaviours (logging, validation, telemetry).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from weebot.application.cqrs.base import (
    CommandHandler,
    CommandResult,
    QueryHandler,
    QueryResult,
)
from weebot.application.cqrs.commands import (
    ArchiveSessionCommand,
    CancelSessionCommand,
    CompactMemoryCommand,
    SummarizeCommand,
    CreatePlanCommand,
    ExecuteStepCommand,
    ProcessMessageCommand,
    UpdatePlanCommand,
)
from weebot.application.cqrs.queries import (
    GetSessionQuery,
    GetSessionStatusQuery,
    ListSessionsQuery,
    GetSessionHistoryQuery,
    GetPlanQuery,
    SearchSessionsQuery,
    GetSimilarSessionsQuery,
    GetActiveTasksQuery,
)
from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.application.models.tool_collection import ToolCollection


def _empty_tools():
    """Return an empty ToolCollection for handlers that don't need tools."""
    return ToolCollection()


if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.application.services.task_runner import TaskRunner


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------


class CreatePlanHandler(CommandHandler):
    """Executes plan creation through PlannerAgent and returns events.

    Previously this was a pre-flight gate only.  Now it owns the full
    planning call so pipeline behaviours (LoggingBehavior, ValidationBehavior)
    activate on every plan creation.
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        event_bus: EventBusPort | None = None,
    ):
        self._state_repo = state_repo
        self._llm = llm
        self._event_bus = event_bus

    async def handle(self, command: CreatePlanCommand) -> CommandResult:
        from weebot.application.agents.planner import PlannerAgent
        from weebot.domain.models.event import PlanEvent

        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            # Build skill context for the planner from session context
            skill_content = session.context.get("skill_content", "")
            skill_name = session.context.get("skill_name", "")

            planner_cfg = {}
            if command.model:
                planner_cfg["model"] = command.model
            if skill_content:
                planner_cfg["skill_prompt"] = skill_content

            planner = PlannerAgent(
                llm=self._llm,
                event_bus=self._event_bus,
                **planner_cfg,
            )

            events: list[dict] = []
            final_plan = None
            async for event in planner.create_plan(command.prompt):
                events.append(event.model_dump())
                session = session.add_event(event)
                if isinstance(event, PlanEvent) and event.plan is not None:
                    final_plan = event.plan

            # Persist the updated session so SavePolicyBehavior has
            # the latest state to save (handler adds events, behavior saves).
            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "plan": final_plan,
                    "model": command.model,
                    "status": "plan_created",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="PLAN_CREATION_ERROR"
            )


class ExecuteStepHandler(CommandHandler):
    """Executes a plan step through ExecutorAgent and returns events.

    Validates pre-conditions (session, plan, step exist; step not done)
    then delegates to ExecutorAgent.execute_step().
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        tools: ToolCollection,
        event_bus: EventBusPort | None = None,
    ):
        self._state_repo = state_repo
        self._llm = llm
        self._tools = tools
        self._event_bus = event_bus

    async def handle(self, command: ExecuteStepCommand) -> CommandResult:
        from weebot.application.agents.executor import ExecutorAgent
        from weebot.domain.models.session import Session

        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            plan = session.get_last_plan()
            if plan is None:
                return CommandResult.fail(
                    error="No plan exists for this session",
                    error_code="NO_PLAN_FOUND",
                )

            step = next((s for s in plan.steps if s.id == command.step_id), None)
            if step is None:
                return CommandResult.fail(
                    error=f"Step {command.step_id} not found in plan",
                    error_code="STEP_NOT_FOUND",
                )

            if step.is_done():
                return CommandResult.fail(
                    error=f"Step {command.step_id} is already {step.status.value}",
                    error_code="STEP_ALREADY_DONE",
                )

            executor = ExecutorAgent(
                llm=self._llm,
                tools=self._tools,
                event_bus=self._event_bus,
                model=command.model,
            )

            events: list[dict] = []
            async for event in executor.execute_step(plan, step):
                events.append(event.model_dump())

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "step_id": command.step_id,
                    "events": events,
                    "status": "step_executed",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="STEP_EXECUTION_ERROR"
            )


class UpdatePlanHandler(CommandHandler):
    """Executes plan update through PlannerAgent and returns events."""

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
        event_bus: EventBusPort | None = None,
    ):
        self._state_repo = state_repo
        self._llm = llm
        self._event_bus = event_bus

    async def handle(self, command: UpdatePlanCommand) -> CommandResult:
        from weebot.application.agents.planner import PlannerAgent
        from weebot.domain.models.event import PlanEvent
        from weebot.domain.models.plan import Plan

        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            plan = session.get_last_plan()
            if plan is None:
                return CommandResult.fail(
                    error="No plan exists for this session",
                    error_code="NO_PLAN_FOUND",
                )

            planner = PlannerAgent(
                llm=self._llm,
                event_bus=self._event_bus,
                model=command.model if hasattr(command, 'model') else None,
            )

            # Find the last completed or failed step
            last_step = next(
                (s for s in reversed(plan.steps) if s.is_done()),
                None,
            )
            if last_step is None and plan.steps:
                last_step = plan.steps[0]

            events: list[dict] = []
            updated_plan = None
            if last_step:
                async for event in planner.update_plan(plan, last_step):
                    events.append(event.model_dump())
                    session = session.add_event(event)
                    if isinstance(event, PlanEvent) and event.plan is not None:
                        updated_plan = event.plan

            # Persist the updated session so SavePolicyBehavior has
            # the latest state to save.
            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "plan": updated_plan,
                    "reason": command.reason,
                    "status": "plan_updated",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="PLAN_UPDATE_ERROR"
            )


class CancelSessionHandler(CommandHandler):
    """Cancel a running session via the TaskRunner."""

    def __init__(self, task_runner: TaskRunner):
        self._task_runner = task_runner

    async def handle(self, command: CancelSessionCommand) -> CommandResult:
        try:
            success = await self._task_runner.cancel_session(command.session_id)
            if success:
                return CommandResult.ok(
                    data={
                        "session_id": command.session_id,
                        "cancelled": True,
                        "reason": command.reason,
                    }
                )
            return CommandResult.fail(
                error=f"Session {command.session_id} not found or not active",
                error_code="SESSION_NOT_ACTIVE",
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="CANCEL_ERROR"
            )


class CompactMemoryHandler(CommandHandler):
    """Compact session memory by removing old events."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo
        self._compactor = MemoryCompactor()

    async def handle(self, command: CompactMemoryCommand) -> CommandResult:
        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            before_count = len(session.events)
            session = self._compactor.compact_session(session)
            after_count = len(session.events)

            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events_before": before_count,
                    "events_after": after_count,
                    "events_removed": before_count - after_count,
                    "status": "compacted",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="COMPACTION_ERROR"
            )


class ProcessMessageHandler(CommandHandler):
    """Process a chat message through ChatAgent and return events.

    This handler owns the ChatAgent call so pipeline behaviours
    (LoggingBehavior, ValidationBehavior) activate on every message.
    """

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        llm: LLMPort,
    ):
        self._state_repo = state_repo
        self._llm = llm

    async def handle(self, command: ProcessMessageCommand) -> CommandResult:
        from weebot.application.agents.chat_agent import ChatAgent

        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            agent = ChatAgent(
                llm=self._llm,
                model=command.model or None,
            )
            # Reconstruct MessageEvent list from history dicts
            history = []
            for h in command.history:
                from weebot.domain.models.event import MessageEvent
                history.append(MessageEvent(
                    role=h.get("role", "user"),
                    message=h.get("message", h.get("content", "")),
                ))

            events: list[dict] = []
            async for event in agent.respond(command.message, history):
                events.append(event.model_dump())

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "exchange_count": command.exchange_count + 1,
                    "status": "message_processed",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="CHAT_ERROR"
            )


class SummarizeHandler(CommandHandler):
    """Generate a final summary via the executor agent through the mediator."""

    def __init__(self, llm: LLMPort, state_repo: StateRepositoryPort | None = None):
        self._llm = llm
        self._state_repo = state_repo

    async def handle(self, command: SummarizeCommand) -> CommandResult:
        from weebot.application.agents.executor import ExecutorAgent

        try:
            # Load session if state_repo is available (best-effort —
            # the flow state also persists via _emit, but direct
            # callers of this handler need their own persistence).
            if self._state_repo:
                session = await self._state_repo.load_session(command.session_id)
            else:
                session = None

            executor = ExecutorAgent(llm=self._llm)
            events: list[dict] = []
            async for event in executor.summarize():
                events.append(event.model_dump())
                if session is not None:
                    session = session.add_event(event)

            if session is not None:
                await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "events": events,
                    "status": "summarized",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="SUMMARIZE_ERROR"
            )


class ArchiveSessionHandler(CommandHandler):
    """Archive a completed session."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, command: ArchiveSessionCommand) -> CommandResult:
        try:
            session = await self._state_repo.load_session(command.session_id)
            if session is None:
                return CommandResult.fail(
                    error=f"Session {command.session_id} not found",
                    error_code="SESSION_NOT_FOUND",
                )

            from datetime import datetime, timezone

            # Mark as archived via context flag
            session = session.model_copy(
                update={
                    "context": session.context.model_copy(update={
                        "archived": True,
                        "archived_at": datetime.now(timezone.utc).isoformat(),
                        "archive_ttl_days": command.ttl_days,
                    })
                }
            )
            await self._state_repo.save_session(session)

            return CommandResult.ok(
                data={
                    "session_id": command.session_id,
                    "ttl_days": command.ttl_days,
                    "status": "archived",
                }
            )
        except Exception as exc:
            return CommandResult.fail(
                error=str(exc), error_code="ARCHIVE_ERROR"
            )


# ---------------------------------------------------------------------------
# Query Handlers — imported from handlers/ subdirectory
# ---------------------------------------------------------------------------
from weebot.application.cqrs.handlers.query_handlers import (
    GetSessionHandler,
    ListSessionsHandler,
    GetSessionStatusHandler,
    GetSessionHistoryHandler,
    GetPlanHandler,
    SearchSessionsHandler,
    GetSimilarSessionsHandler,
    GetActiveTasksHandler,
)


# ---------------------------------------------------------------------------
# Handler Registration Helper
# ---------------------------------------------------------------------------
def register_default_handlers(
    mediator,
    state_repo: StateRepositoryPort,
    task_runner: TaskRunner = None,
    *,
    llm=None,
    tools=None,
    event_bus=None,
) -> None:
    """Register all default command and query handlers with a mediator.

    Args:
        mediator: The Mediator instance.
        state_repo: State repository for persistence operations.
        task_runner: Optional task runner for task management.
        llm: LLMPort for agent handlers (required for CreatePlanHandler etc.).
        tools: ToolCollection for execution handler.
        event_bus: Optional EventBusPort for agent event publishing.
    """
    from weebot.application.cqrs.mediator import Mediator

    if not isinstance(mediator, Mediator):
        raise ValueError("mediator must be a Mediator instance")

    # --- Command handlers ---
    # Handlers that call agents need llm and tools; fall back to validation-only
    # if these aren't provided (legacy compatibility).
    if llm is not None:
        mediator.register_command_handler(
            CreatePlanCommand,
            CreatePlanHandler(state_repo, llm, event_bus),
        )
        mediator.register_command_handler(
            ProcessMessageCommand,
            ProcessMessageHandler(state_repo, llm),
        )
        mediator.register_command_handler(
            ExecuteStepCommand,
            ExecuteStepHandler(state_repo, llm, tools or _empty_tools(), event_bus),
        )
        mediator.register_command_handler(
            UpdatePlanCommand,
            UpdatePlanHandler(state_repo, llm, event_bus),
        )
    else:
        mediator.register_command_handler(
            CreatePlanCommand, CreatePlanHandler(state_repo)
        )
        mediator.register_command_handler(
            ExecuteStepCommand, ExecuteStepHandler(state_repo)
        )
        mediator.register_command_handler(
            UpdatePlanCommand, UpdatePlanHandler(state_repo)
        )
    mediator.register_command_handler(
        CompactMemoryCommand, CompactMemoryHandler(state_repo)
    )
    mediator.register_command_handler(
        ArchiveSessionCommand, ArchiveSessionHandler(state_repo)
    )
    if llm is not None:
        mediator.register_command_handler(
            SummarizeCommand, SummarizeHandler(llm, state_repo)
        )

    if task_runner:
        mediator.register_command_handler(
            CancelSessionCommand, CancelSessionHandler(task_runner)
        )

    # --- Query handlers ---
    mediator.register_query_handler(
        GetSessionQuery, GetSessionHandler(state_repo)
    )
    mediator.register_query_handler(
        ListSessionsQuery, ListSessionsHandler(state_repo)
    )
    mediator.register_query_handler(
        GetSessionStatusQuery,
        GetSessionStatusHandler(state_repo, task_runner),
    )
    mediator.register_query_handler(
        GetSessionHistoryQuery, GetSessionHistoryHandler(state_repo)
    )
    mediator.register_query_handler(
        GetPlanQuery, GetPlanHandler(state_repo)
    )
    mediator.register_query_handler(
        SearchSessionsQuery, SearchSessionsHandler(state_repo)
    )
    mediator.register_query_handler(
        GetSimilarSessionsQuery, GetSimilarSessionsHandler(state_repo)
    )
    mediator.register_query_handler(
        GetActiveTasksQuery,
        GetActiveTasksHandler(task_runner) if task_runner
        else GetActiveTasksHandler(TaskRunner(state_repo=state_repo)),
    )
