"""The closing event says whether the run worked, so the UI cannot call a failure done.

Found on live session de5d0990: the session was stored as ``failed``, but the web UI
rendered its ``done`` event as "Session completed", because the event carried nothing.
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states.completed import CompletedState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import DoneEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step, StepStatus
from weebot.domain.models.session import Session


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


async def _done(status: StepStatus) -> DoneEvent:
    # A second, pending step keeps the plan unfinished, so the flow loads it and runs.
    steps = [Step(id="s1", description="a", status=status), Step(id="s2", description="b")]
    plan = Plan(title="T", steps=steps)
    s = Session(id="s1", task="t").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json"))
    )
    flow = PlanActFlow(
        PlanActFlowConfig(llm=_LLM(), tools=ToolCollection(), session=s, max_iterations=4)
    )
    orig, started = flow.set_state, {"done": False}

    def _first(state):
        if not started["done"]:
            started["done"] = True
            if status is StepStatus.COMPLETED:  # a run that worked finished every step (R06)
                flow._plan = flow._plan.update_step_status("s2", StepStatus.COMPLETED)
            return orig(CompletedState())
        return orig(state)

    flow.set_state = _first
    return next(e for e in [e async for e in flow.run("t")] if isinstance(e, DoneEvent))


async def test_a_failed_run_ends_with_a_failed_done():
    assert (await _done(StepStatus.FAILED)).status == "failed"


async def test_a_run_that_worked_ends_with_a_completed_done():
    assert (await _done(StepStatus.COMPLETED)).status == "completed"


def test_old_done_events_still_load():
    assert DoneEvent.model_validate({"type": "done"}).status is None
