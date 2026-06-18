"""ExecuteStepHandler — handles ExecuteStep command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import ExecuteStepCommand

from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import AgentEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session

def _empty_tools():
    """Return an empty ToolCollection for handlers that don't need tools."""
    return ToolCollection()

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
            import traceback
            detail = traceback.format_exc()
            # Log at module level — handler may not have a logger wired
            import logging as _logging
            _logging.getLogger(__name__).error(
                "ExecuteStepHandler failed: %s\n%s",
                exc, detail,
            )
            return CommandResult.fail(
                error=f"{type(exc).__name__}: {exc}", error_code="STEP_EXECUTION_ERROR"
            )

