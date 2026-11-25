"""Re-run a step: the one place that knows what a retry has to do.

ExecuteStepHandler reads the plan from the SAVED session and refuses a step it still sees
as done. A retry that only changed the flow's in-memory plan was therefore refused, and the
step never re-ran (audit X5). A retry has to reset the step AND persist the plan, so both
halves live here for the failure retry, the quality retry and the code-review revise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weebot.application.flows.states.base import StateId, new_state
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import PlanStatus, Step, StepStatus

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow


async def retry_step(
    context: PlanActFlow, step: Step, *, description: str | None = None
) -> PlanEvent:
    """Reset *step* to PENDING, persist the plan, and send the flow back to EXECUTING.

    *description* replaces the step's text (a hint appended by the caller). Returns the
    PlanEvent it emitted, for a caller that also yields it.
    """
    update: dict = {"status": StepStatus.PENDING, "retry_count": step.retry_count + 1}
    if description is not None:
        update["description"] = description
    context._plan = context._plan.replace_step(step.id, step.model_copy(update=update))

    event = PlanEvent(status=PlanStatus.UPDATED, plan=context._plan.model_dump(mode="json"))
    await context._emit(event)  # saves the session, and with it the plan the handler reads
    context.set_state(new_state(StateId.EXECUTING))
    return event
