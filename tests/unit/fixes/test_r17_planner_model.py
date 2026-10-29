"""R17 (audit 2026-10-29): the planner uses its model.

The planner got the flow's ``--model`` override (usually None) and ``_chat_json`` never
passed a model at all, so every plan ran on the adapter's default model, whatever
``ROLE_MODEL_CONFIG["planner"]`` or ``--model`` said. D-R2 (option A): the planner uses
its configured models, Haiku 5.5 first; ``--model`` still wins.
"""

from __future__ import annotations

import pytest

from weebot.application.agents.planner import PlannerAgent
from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.application.models.plan_act_flow_config import PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.config import model_refs
from weebot.config.model_refs import role_primary_model
from weebot.domain.models.session import Session


class _LLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {"content": "{}"}


@pytest.mark.asyncio
async def test_the_planner_sends_its_model():
    llm = _LLM()
    await PlannerAgent(llm=llm, model="vendor/x")._chat_json([{"role": "user", "content": "hi"}])
    assert llm.calls[0]["model"] == "vendor/x"


@pytest.mark.parametrize("override", [None, "vendor/override"])
def test_the_flow_gives_the_planner_its_role_model(override):
    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_LLM(), tools=ToolCollection(), session=Session(id="r17"), model=override
        )
    )
    expected = override or role_primary_model("planner")
    assert expected and flow._planner._model == expected


def test_the_primary_model_skips_free_tiers(monkeypatch):
    monkeypatch.setattr(
        model_refs, "get_model_cascade_for_role", lambda role: ["free/groq/a", "vendor/b"]
    )
    assert role_primary_model("planner") == "vendor/b"
