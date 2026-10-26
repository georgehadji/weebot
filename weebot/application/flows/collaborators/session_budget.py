"""The flow's hard cost limit: ask, pause, or stop (plan 2.4, decision D6).

Extracted from ``PlanActFlow`` so the flow keeps one line per concern. The pure part
(is the limit reached?) is ``SessionCostTermination``; this module is the effectful
shell around it: it asks through the ADR-013 channel and tells the flow what to do.
"""

from __future__ import annotations

from typing import Any

from weebot.application.ports.approval_port import ApprovalOutcome, ToolCallApproval
from weebot.application.services.session_cost import (
    BUDGET_EXCEEDED,
    ask_to_continue,
    budget_prompt,
)
from weebot.application.termination.base import TerminationContext
from weebot.application.termination.conditions import SessionCostTermination
from weebot.domain.models.event import ToolApprovalEvent, WaitForUserEvent


async def budget_gate(flow: Any) -> tuple[str, str]:
    """``("ok" | "wait" | "stop", reason)`` for *flow* (needs ``_cost_meter`` set).

    At the limit a yes grants one more increment; a pending answer pauses the flow
    (resumable, the request is left on ``flow._pending_budget_request``); a no, or no
    one to ask, ends it as ``BUDGET_EXCEEDED``.
    """
    meter = flow._cost_meter
    hard = meter.hard_usd if flow._cost_hard_override is None else flow._cost_hard_override
    if hard <= 0:
        return "ok", ""
    session_id = flow._session.id
    total = meter.total(session_id)
    allowance = hard * (1 + flow._budget_grants)
    reached = SessionCostTermination().check(
        TerminationContext(session_cost_usd=total, session_cost_allowance_usd=allowance)
    )
    if not reached.should_terminate:
        return "ok", ""
    outcome, request = await ask_to_continue(session_id, total, allowance)
    if outcome is ApprovalOutcome.APPROVED:
        flow._budget_grants += 1
        flow._log.info("cost limit $%.2f approved for one more increment", allowance)
        return "ok", ""
    if outcome is ApprovalOutcome.PENDING:
        flow._pending_budget_request = request
        return "wait", budget_prompt(session_id, total, allowance)
    return "stop", f"{BUDGET_EXCEEDED}: refused at ${total:.2f} (limit ${allowance:.2f})"


def pause_events(
    request: ToolCallApproval, prompt: str
) -> tuple[ToolApprovalEvent, WaitForUserEvent]:
    """The two events a paused flow emits: the approval card, then the question."""
    return (
        ToolApprovalEvent(
            tool_name=request.tool_name,
            arguments=request.arguments,
            risk_level=request.guard,
            reason=request.reason,
            prompt=prompt,
            fingerprint=request.fingerprint,
        ),
        WaitForUserEvent(question=prompt),
    )


async def enforce_budget(flow: Any) -> list[Any] | None:
    """Apply the gate to *flow*: events to yield and stop on a pause, else None.

    ``stop`` moves the flow to ``CompletedState`` with the BUDGET_EXCEEDED reason;
    ``wait`` marks the session WAITING (resumable) and returns the approval card and
    question for the flow to yield.
    """
    from weebot.domain.models.session import SessionStatus

    gate, why = await budget_gate(flow)
    if gate == "wait":
        flow._session = flow._session.set_status(SessionStatus.WAITING)
        approval, question = pause_events(flow._pending_budget_request, why)
        await flow._emit(approval)
        return [approval, question]
    if gate == "stop":
        from weebot.application.flows.states.completed import CompletedState

        flow._log.info("Termination condition met: %s", why)
        flow._end_run_span()
        flow.set_state(CompletedState(termination_reason=why))
    return None


def enforce_termination(flow: Any, iteration: int) -> None:
    """Run the flow's composable termination conditions; on a hit, finish via CompletedState.

    Moved out of ``PlanActFlow.run`` unchanged (it is the same family as the cost
    gate above: decide to stop, then hand the flow to its terminal state).
    """
    import time as _term_time

    ctx = TerminationContext(
        iteration=iteration,
        total_tokens=flow.token_usage.get("total_tokens", 0),
        elapsed_seconds=_term_time.monotonic() - flow._flow_started_at,
    )
    for condition in flow._termination_conditions:
        result = condition.check(ctx)
        if result.should_terminate:
            from weebot.application.flows.states.completed import CompletedState

            flow._log.info("Termination condition met: %s", result.reason)
            flow._end_run_span()
            # Run CompletedState this pass; it sets the terminal status, so the loop
            # ends after it.
            flow.set_state(CompletedState(termination_reason=result.reason))
            break
