"""The plan_act_iteration span ends when the run ends, once.

Its only `end()` on the normal path sat in PlanActFlow._maybe_save_checkpoint,
which nothing calls, so a finished run left its span open.
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.session import Session


class _Span:
    ends = 0

    def __init__(self, name):
        self.name = name

    def set_attribute(self, *a):
        pass

    def end(self):
        if self.name == "plan_act_iteration":
            _Span.ends += 1


class _Tracing:
    def start_span(self, name):
        return _Span(name)


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


async def test_a_finished_run_ends_its_span(monkeypatch):
    monkeypatch.setattr("weebot.config.feature_flags.is_enabled",
                        lambda name: name == "OTEL_TRACING_ENABLED")
    _Span.ends = 0
    from weebot.application.flows.states.completed import CompletedState
    from weebot.domain.models.event import PlanEvent
    from weebot.domain.models.plan import Plan, PlanStatus, Step

    plan = Plan(title="T", steps=[Step(id="s1", description="a"), Step(id="s2", description="b")])
    s = Session(id="s", task="t").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump(mode="json")))
    flow = PlanActFlow(PlanActFlowConfig(llm=_LLM(), tools=ToolCollection(), session=s,
                                         max_iterations=3, tracing_port=_Tracing()))
    orig = flow.set_state
    flow.set_state = lambda st: orig(CompletedState())  # end normally, first pass
    _ = [e async for e in flow.run("t")]
    assert _Span.ends == 1
