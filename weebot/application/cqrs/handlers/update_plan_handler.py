"""UpdatePlanHandler — handles UpdatePlan command.

Split from weebot/application/cqrs/handlers.py during architecture remediation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from weebot.application.cqrs.base import CommandHandler, CommandResult

if TYPE_CHECKING:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.commands import UpdatePlanCommand

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

