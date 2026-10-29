"""R06 (audit 2026-10-29): a run with unverified or never-run steps does not end COMPLETED.

CompletedState judged the run by ``failed_steps()`` alone, so a step the verifier marked
UNVERIFIED, or a step that never ran (every model tripped, the iteration cap hit), left
the session COMPLETED and the UI said "Session completed". Per owner decision D-R1 such a
run ends FAILED, with a reason that names those steps.
"""

from __future__ import annotations

import types

import pytest

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states.completed import CompletedState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import DoneEvent, ErrorEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanOutcome, PlanStatus, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus


def _plan(*statuses: StepStatus) -> Plan:
    return Plan(
        title="T",
        steps=[Step(id=f"s{i}", description=f"step {i}", status=st) for i, st in enumerate(statuses)],
    )


@pytest.mark.parametrize(
    ("statuses", "outcome"),
    [
        ((StepStatus.COMPLETED, StepStatus.COMPLETED), PlanOutcome.SUCCEEDED),
        ((StepStatus.COMPLETED, StepStatus.FAILED), PlanOutcome.FAILED),
        ((StepStatus.UNVERIFIED, StepStatus.FAILED), PlanOutcome.FAILED),
        ((StepStatus.COMPLETED, StepStatus.UNVERIFIED), PlanOutcome.INCOMPLETE),
        ((StepStatus.COMPLETED, StepStatus.PENDING), PlanOutcome.INCOMPLETE),
        ((StepStatus.RUNNING,), PlanOutcome.INCOMPLETE),
    ],
)
def test_plan_outcome(statuses, outcome):
    assert _plan(*statuses).outcome() is outcome


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


async def _finish(plan: Plan):
    session = Session(id="sess", task="t").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json"))
    )
    flow = PlanActFlow(PlanActFlowConfig(llm=_LLM(), tools=ToolCollection(), session=session))
    flow._plan = plan
    events = [e async for e in CompletedState().execute(flow, "")]
    return flow, events


@pytest.mark.asyncio
@pytest.mark.parametrize("left", [StepStatus.UNVERIFIED, StepStatus.PENDING])
async def test_an_incomplete_run_ends_failed_and_names_the_steps(left):
    flow, events = await _finish(_plan(StepStatus.COMPLETED, left))
    assert flow._session.status == SessionStatus.FAILED
    assert flow._plan.status == PlanStatus.FAILED
    assert next(e for e in events if isinstance(e, DoneEvent)).status == "failed"
    errors = [e.error for e in events if isinstance(e, ErrorEvent)]
    assert errors and "s1" in errors[0] and "step 1" in errors[0]


@pytest.mark.asyncio
async def test_a_run_where_every_step_completed_stays_completed():
    flow, events = await _finish(_plan(StepStatus.COMPLETED, StepStatus.COMPLETED))
    assert flow._session.status == SessionStatus.COMPLETED
    assert flow._plan.status == PlanStatus.COMPLETED
    assert next(e for e in events if isinstance(e, DoneEvent)).status == "completed"
    assert not any(isinstance(e, ErrorEvent) for e in events)
