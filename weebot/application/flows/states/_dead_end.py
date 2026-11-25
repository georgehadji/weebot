"""End a run that cannot continue: FAILED, with the reason on the session.

A state that yielded an ErrorEvent and returned without a transition or a terminal status left
the session RUNNING in the same state, so the flow loop re-entered it up to `max_iterations`
times, repeating any LLM call, and ended `MAX_ITERATIONS` with a reason that blamed the loop,
not the cause (audit M3-D1). `fail_run` is the one way out of such a state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.session import FAILURE_REASON_KEY, SessionStatus

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

async def fail_run(context: PlanActFlow, error: str, error_code: str = "") -> ErrorEvent:
    """Mark the session FAILED with *error* as its reason, emit the error and return it.

    Emitted, not only yielded, so the bus and the stored transcript carry it; the caller
    still yields it to the stream.
    """
    session = context._session
    extra = {**session.context.extra, FAILURE_REASON_KEY: error[:500]}
    session = session.model_copy(
        update={"context": session.context.model_copy(update={"extra": extra})}
    )
    context._session = session.set_status(SessionStatus.FAILED)
    event = ErrorEvent(error=error, error_code=error_code)
    await context._emit(event)
    return event
