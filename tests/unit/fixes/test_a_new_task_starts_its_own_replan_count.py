"""A finished run clears its replan count, so the next task in the session starts at 0.

Found by review of the replan cap: the count lives in the session so a resume keeps it,
but only a completed step or the cap itself cleared it. A run that ended any other way
(no revised plan, budget stop) left its count for the next task, which then stopped
after fewer replans than the cap allows.
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states._step_outcome import _REPLANS_KEY
from weebot.application.flows.states.completed import CompletedState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step, StepStatus
from weebot.domain.models.session import Session


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


async def test_a_run_that_ends_failed_clears_the_count():
    steps = [
        Step(id="s1", description="a", status=StepStatus.FAILED),
        Step(id="s2", description="b"),
    ]
    plan = Plan(title="T", steps=steps)
    s = Session(id="s1", task="t").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json"))
    )
    s = s.model_copy(
        update={"context": s.context.model_copy(update={"extra": {_REPLANS_KEY: 2}})}
    )
    flow = PlanActFlow(
        PlanActFlowConfig(llm=_LLM(), tools=ToolCollection(), session=s, max_iterations=4)
    )
    orig, started = flow.set_state, {"done": False}

    def _first(state):
        if not started["done"]:
            started["done"] = True
            return orig(CompletedState())
        return orig(state)

    flow.set_state = _first
    [e async for e in flow.run("t")]
    assert not flow._session.context.get(_REPLANS_KEY)
