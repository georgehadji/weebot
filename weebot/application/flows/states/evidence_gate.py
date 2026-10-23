"""Per-step evidence gate for ExecutingState (LongHorizon-Harness E1, F69)."""

from __future__ import annotations

import logging

from weebot.domain.models.audit import AuditVerdict
from weebot.domain.models.event import PlanEvent, ToolEvent
from weebot.domain.models.plan import Step, StepStatus

logger = logging.getLogger(__name__)


async def evidence_gate(
    context, step: Step, step_events: list, step_elapsed: float
) -> PlanEvent | None:
    """Run the per-step evidence audit. On a gap, send the step back (retry
    once, then UNVERIFIED), emit the changed plan and return that event;
    None when the step passes or no auditor is wired.

    The downgrade used to change only ``context._plan``: resume rebuilds
    statuses from events, so the step came back COMPLETED (F69).
    """
    from weebot.application.flows.states.executing import ExecutingState
    from weebot.application.flows.states.updating import UpdatingState
    from weebot.domain.models.plan import PlanStatus

    _step_audit_service = getattr(context, "_step_audit_service", None)
    if _step_audit_service is None:
        return None
    _step_tool_events = [e for e in step_events if isinstance(e, ToolEvent)]
    _audit_report = await _step_audit_service.audit_step(
        step=step, events=_step_tool_events, session_id=context._session.id
    )
    if _audit_report.verdict == AuditVerdict.PASS:
        return None
    logger.warning(
        "Step '%s' failed evidence audit (%s): %s",
        step.id,
        _audit_report.verdict.value,
        _audit_report.summary,
    )
    if step.retry_count < 1:
        updated_step = step.model_copy(
            update={
                "description": f"{step.description}\n[Evidence gap: {_audit_report.summary}]",
                "retry_count": 1,
                "status": StepStatus.PENDING,
            }
        )
        context._plan = context._plan.replace_step(step.id, updated_step)
        context.set_state(ExecutingState())
    else:
        context._plan = context._plan.update_step_status(
            step.id, StepStatus.UNVERIFIED, result=_audit_report.summary
        )
        logger.info("Step %s UNVERIFIED after retry (%.1fs)", step.id, step_elapsed)
        context.set_state(UpdatingState())
    plan_event = PlanEvent(
        status=PlanStatus.UPDATED, plan=context._plan.model_dump(mode="json")
    )
    await context._emit(plan_event)
    return plan_event
