"""End a run that cannot continue: FAILED, with the reason on the session.

A state that yielded an ErrorEvent and returned without a transition or a terminal status left
the session RUNNING in the same state, so the flow loop re-entered it up to `max_iterations`
times, repeating any LLM call, and ended `MAX_ITERATIONS` with a reason that blamed the loop,
not the cause (audit M3-D1). `fail_run` is the one way out of such a state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.session import SessionStatus

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

_FAILURE_KEY = "failure_reason"  # the key TaskRunner reads for a FAILED session


def fail_run(context: PlanActFlow, error: str, error_code: str = "") -> ErrorEvent:
    """Mark the session FAILED with *error* as its reason; the caller yields the event."""
    session = context._session
    extra = {**session.context.extra, _FAILURE_KEY: error[:500]}
    session = session.model_copy(
        update={"context": session.context.model_copy(update={"extra": extra})}
    )
    context._session = session.set_status(SessionStatus.FAILED)
    return ErrorEvent(error=error, error_code=error_code)
