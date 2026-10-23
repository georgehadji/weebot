"""A step the evidence audit sends back is saved as a plan change (F69).

The executor yields a COMPLETED StepEvent; the evidence audit then reset the
step to PENDING (retry) or UNVERIFIED on `context._plan` only, with no event.
On resume `get_last_plan` rebuilds statuses from events, so the step came back
COMPLETED and was skipped.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from weebot.application.flows.states.executing import ExecutingState
from weebot.domain.models.audit import AuditReport, AuditVerdict
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session


def _context(retry_count):
    step = Step(id="s1", description="write out.py", status=StepStatus.COMPLETED,
                result="done", retry_count=retry_count)
    ctx = MagicMock()
    ctx._session = Session(id="sess")
    ctx._plan = Plan(goal="g", steps=[step])
    ctx._emit = AsyncMock()
    ctx._step_audit_service = MagicMock()
    ctx._step_audit_service.audit_step = AsyncMock(
        return_value=AuditReport(session_id="sess", verdict=AuditVerdict.FAIL,
                                 violations=[], summary="out.py missing", score=0.0)
    )
    return ctx, step


async def test_a_retry_after_an_evidence_gap_is_emitted():
    ctx, step = _context(retry_count=0)
    event = await ExecutingState()._evidence_gate(ctx, step, [], 0.0)
    assert isinstance(event, PlanEvent)
    ctx._emit.assert_awaited_once_with(event)
    assert event.plan["steps"][0]["status"] == StepStatus.PENDING.value


async def test_an_unverified_step_is_emitted():
    ctx, step = _context(retry_count=1)
    event = await ExecutingState()._evidence_gate(ctx, step, [], 0.0)
    assert event.plan["steps"][0]["status"] == StepStatus.UNVERIFIED.value
    ctx._emit.assert_awaited_once_with(event)


async def test_a_passing_audit_changes_nothing():
    ctx, step = _context(retry_count=0)
    ctx._step_audit_service.audit_step.return_value = AuditReport(
        session_id="sess", verdict=AuditVerdict.PASS, violations=[], summary="", score=1.0
    )
    assert await ExecutingState()._evidence_gate(ctx, step, [], 0.0) is None
    ctx._emit.assert_not_awaited()
