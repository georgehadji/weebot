"""Updating state for Plan-Act flow."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, StepStatus

logger = logging.getLogger(__name__)

class UpdatingState(FlowState):
    """Handles the updating of the execution plan after a step completes."""
    status = AgentStatus.UPDATING

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
        # --- Build failure context for planner ---
        failure_msg = ""
        if last_step.status == StepStatus.FAILED and last_step.result:
            failure_msg = f" | Failure: {str(last_step.result)[:500]}"

        # --- CQRS: execute plan update through mediator ---
        if context._mediator:
            import time as _time
            _update_t0 = _time.monotonic()
            from weebot.application.cqrs.commands import UpdatePlanCommand
            from weebot.config.model_refs import MODEL_BUDGET
            cmd_result = await context._mediator.send(
                UpdatePlanCommand(
                    session_id=context._session.id,
                    updates={
                        "last_step_id": last_step.id,
                        "failure_context": str(last_step.result or ""),
                    },
                    reason=(
                        f"Step {last_step.id} {last_step.status.value}{failure_msg}. "
                        "Generate a NEW approach that does not repeat the same strategy."
                    ),
                    model=context._model or MODEL_BUDGET,
                )
            )
            _update_elapsed = _time.monotonic() - _update_t0
            if not cmd_result.success:
                yield ErrorEvent(
                    error=f"Plan update rejected: {cmd_result.error}"
                )
                context.set_state(ExecutingState())
                return

            logger.info("Plan updated in %.1fs", _update_elapsed)
            # Consume events from the mediator result.
            # Consume events via shared reconstructor.
            from weebot.application.cqrs.event_reconstructor import reconstruct_events
            for event in reconstruct_events(cmd_result.data.get("events", [])):
                await context._emit(event)
                yield event
                if isinstance(event, PlanEvent) and event.status == PlanStatus.UPDATED:
                    context._plan = Plan.model_validate(event.plan)
                    update_success = True
                    # Hook: post_plan_updated
                    if getattr(context, "_hooks", None) is not None:
                        await context._hooks.execute_hooks("post_plan_updated", {
                            "session_id": context._session.id,
                            "plan": context._plan,
                            "step_count": len(context._plan.steps),
                            "elapsed_ms": _update_elapsed * 1000,
                            "reason": f"Step {last_step.id} {last_step.status.value}",
                        })

            # Also check for plan in result top-level
            if not update_success and cmd_result.data.get("plan"):
                context._plan = Plan.model_validate(cmd_result.data["plan"])
                update_success = True
        else:
            # Fallback: direct agent call
            import warnings
            warnings.warn(
                "UpdatingState: no mediator, using direct planner call. "
                "Pipeline behaviors (logging, validation, telemetry) will NOT fire.",
                DeprecationWarning, stacklevel=2,
            )
            # ── HyperAgents Enhancement 3: inject avoidance prompt ──
            from weebot.application.services.plan_novelty import PlanNoveltyTracker
            tracker = PlanNoveltyTracker()
            plans = context._plan_history.get_all()  # snapshot history
            avoidance = tracker.avoidance_prompt(plans) if plans else ""

            fc = str(last_step.result or "")
            if avoidance:
                fc = f"{fc}\n{avoidance}"

            async for event in context._planner.update_plan(
                context._plan, last_step, failure_context=fc,
            ):
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
