"""A run whose plan has a failed step stops after CompletedState.

CompletedState marks the session FAILED and its own status is COMPLETED, not
IDLE. The run loop broke only on a COMPLETED or WAITING session, so it ran
CompletedState again every pass until max_iterations: repeated terminal plan
events, then a "Max iterations" error on a run that had already ended.
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.flows.states.completed import CompletedState
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import ErrorEvent, PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step, StepStatus
from weebot.domain.models.session import Session


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


async def test_completed_state_with_a_failed_step_runs_once():
    plan = Plan(title="T", steps=[Step(id="s1", description="a", status=StepStatus.FAILED),
                                  Step(id="s2", description="b")])
    s = Session(id="s1", task="t").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json")))
    flow = PlanActFlow(PlanActFlowConfig(
        llm=_LLM(), tools=ToolCollection(), session=s, max_iterations=4))

    # The unfinished plan routes to ExecutingState; start the real loop at
    # CompletedState instead, as if the last step had just failed.
    orig = flow.set_state
    started = {"done": False}

    def _first(state):
        if not started["done"]:
            started["done"] = True
            return orig(CompletedState())
        return orig(state)

    flow.set_state = _first
    events = [e async for e in flow.run("t")]

    terminal = [e for e in events if isinstance(e, PlanEvent) and e.status == PlanStatus.FAILED]
    assert len(terminal) == 1
    assert not any(isinstance(e, ErrorEvent) and "Max iterations" in (e.error or "") for e in events)
