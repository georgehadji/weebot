"""EventPublisher reads the flow's current plan, not the one from construction.

`_emit` synced the publisher's session on every call but not its plan, so truth
binding and checkpoints read the plan as it was at the first emit (often None).
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


async def test_a_later_plan_reaches_the_publisher():
    flow = PlanActFlow(PlanActFlowConfig(llm=_LLM(), tools=ToolCollection(),
                                         session=Session(id="s", task="t")))
    await flow._emit(MessageEvent(role="assistant", message="first"))
    flow._plan = Plan(title="P", steps=[Step(id="s1", description="a")])
    await flow._emit(MessageEvent(role="assistant", message="second"))
    assert flow._get_event_publisher()._plan is flow._plan
