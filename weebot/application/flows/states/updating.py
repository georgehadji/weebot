"""Updating state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, StepStatus

logger = logging.getLogger(__name__)

class UpdatingState(FlowState):
    """Handles the updating of the execution plan after a step completes."""

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState

        if context._plan is None:
            yield ErrorEvent(error="No plan available during update")
            return

        # Find the most recently completed or failed step
        last_step = next(
            (s for s in reversed(context._plan.steps) if s.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.RUNNING)),
            None,
        )

        if last_step is None:
            # If no steps have even started, we might be here due to an immediate failure
            # Try using the first step as context if available
            if context._plan.steps:
                last_step = context._plan.steps[0]
            else:
                yield ErrorEvent(error="No steps found in plan for update")
                return

        update_success = False
        # --- CQRS: execute plan update through mediator ---
        if context._mediator:
            from weebot.application.cqrs.commands import UpdatePlanCommand
            cmd_result = await context._mediator.send(
                UpdatePlanCommand(
                    session_id=context._session.id,
                    updates={"last_step_id": last_step.id},
                    reason=f"Step {last_step.id} completed: {last_step.status.value}",
                    model=context._model or "",
                )
            )
            if not cmd_result.success:
                yield ErrorEvent(
                    error=f"Plan update rejected: {cmd_result.error}"
                )
                context.set_state(ExecutingState())
                return

            # Consume events from the mediator result.
            # Use TypeAdapter (not model_validate) because AgentEvent is
            # a Union type, not a BaseModel — model_validate raises on Unions.
            from pydantic import TypeAdapter
            from weebot.domain.models.event import AgentEvent as AE
            _ev_adapter = TypeAdapter(AE)
            for event_dict in cmd_result.data.get("events", []):
                try:
                    event = _ev_adapter.validate_python(event_dict)
                except Exception:
                    logger.warning("Skipping unparseable event: %s", str(event_dict)[:200])
                    continue
                await context._emit(event)
                yield event
                if isinstance(event, PlanEvent) and event.status == PlanStatus.UPDATED:
                    context._plan = Plan.model_validate(event.plan)
                    update_success = True

            # Also check for plan in result top-level
            if not update_success and cmd_result.data.get("plan"):
                context._plan = Plan.model_validate(cmd_result.data["plan"])
                update_success = True
        else:
            # Fallback: direct agent call
            async for event in context._planner.update_plan(context._plan, last_step):
                await context._emit(event)
                yield event
                if isinstance(event, PlanEvent) and event.status == PlanStatus.UPDATED:
                    context._plan = Plan.model_validate(event.plan)
                    update_success = True
                elif isinstance(event, ErrorEvent):
                    logger.warning("Plan update failed, continuing with existing plan")
                    update_success = True

        if not update_success:
            logger.warning("Plan update did not produce valid result, continuing")

        # Mark the failing/running step as handled if we got an update
        if last_step and last_step.status in (StepStatus.FAILED, StepStatus.RUNNING):
             context._plan = context._plan.update_step_status(last_step.id, StepStatus.COMPLETED, result="Handled by plan update")

        context._snapshot_plan()
        context.set_state(ExecutingState())
