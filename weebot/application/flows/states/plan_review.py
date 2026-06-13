"""PlanReviewState — pauses flow for the user to inspect and approve the plan.

Emits a PlanReviewEvent (renders as a structured plan card in the UI)
followed by a WaitForUserEvent.  The user types "approve" / "yes" to proceed
or describes changes; the response is handled by PlanActFlow.run() on resume.

Control flow:
  1. This state emits events and sets ``plan_pending_approval`` in session context.
  2. On resume, PlanActFlow.run() reads the flag and the user's response, then
     routes to ExecutingState (approve) or PlanningState (modify).
  3. This state is NOT re-entered on resume — the routing is done by run().
"""
from __future__ import annotations

import logging
import os
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.domain.models.event import AgentEvent, ErrorEvent, PlanReviewEvent, WaitForUserEvent

_log = logging.getLogger(__name__)

_APPROVE_TOKENS = frozenset({
    "approve", "approved", "yes", "ok", "proceed", "continue",
    "go", "go ahead", "run", "start", "lgtm", "y", "do it",
})


def next_state_after_plan(min_steps: int = 1):
    """Return PlanReviewState or ExecutingState based on the feature flag.

    Call this from any state that previously transitioned to ExecutingState
    after plan creation/critique to insert the plan review gate.
    """
    from weebot.application.flows.states.executing import ExecutingState

    enabled = os.getenv("WEEBOT_PLAN_REVIEW_ENABLED", "true").lower() in ("true", "1", "yes")
    if not enabled:
        return ExecutingState()
    return PlanReviewState(min_steps=min_steps)


class PlanReviewState(FlowState):
    """Pauses execution for the user to review the proposed plan."""

    status = AgentStatus.PLANNING  # reuse PLANNING — no new enum value needed

    def __init__(self, min_steps: int = 1) -> None:
        self._min_steps = min_steps

    async def execute(
        self, context: "PlanActFlow", prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState

        if context._plan is None:
            yield ErrorEvent(error="PlanReviewState entered with no plan")
            context.set_state(ExecutingState())
            return

        plan = context._plan

        # Auto-approve tiny plans to avoid friction on trivial tasks
        if len(plan.steps) < self._min_steps:
            _log.debug(
                "Plan review: auto-approving %d-step plan (min_steps=%d)",
                len(plan.steps), self._min_steps,
            )
            context.set_state(ExecutingState())
            return

        _log.info(
            "Plan review: presenting %d-step plan '%s' to user",
            len(plan.steps), plan.title,
        )

        yield PlanReviewEvent(
            plan_data=plan.model_dump(mode="json"),
            step_count=len(plan.steps),
        )

        # Mark plan as pending approval in session context (extra dict)
        _new_extra = {**context._session.context.extra, "plan_pending_approval": True}
        _new_ctx = context._session.context.model_copy(update={"extra": _new_extra})
        context._session = context._session.model_copy(update={"context": _new_ctx})

        yield WaitForUserEvent(
            question=(
                f"Plan ready ({len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}):\n"
                + "\n".join(f"  {i+1}. {s.description}" for i, s in enumerate(plan.steps[:8]))
                + ("\n  ..." if len(plan.steps) > 8 else "")
                + "\n\nType 'approve' to start execution, or describe changes / constraints to add."
            )
        )
