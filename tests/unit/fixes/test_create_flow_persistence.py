"""`factories.create_flow` hands each flow the container's session savers.

Plan-act flows never got the retrying `session_persistence` adapter: the
attribute was hardcoded to None, so every save went straight to
`state_repo.save_session` with no retry. Chat flows built here got neither the
adapter nor a `state_repo`, so they did not persist at all.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from weebot.application.models.tool_collection import ToolCollection
from weebot.domain.models.session import Session
from weebot.interfaces import factories


def _fake_cached(adapter):
    return lambda key: adapter if key == "session_persistence" else None


def test_plan_act_flows_get_the_retrying_adapter(monkeypatch):
    adapter = object()
    monkeypatch.setattr(factories, "_cached", _fake_cached(adapter))
    flow = factories.create_flow(
        "plan_act", session=Session(id="p1", task="t"), llm=MagicMock(), tools=ToolCollection()
    )
    assert flow._get_persistence_adapter() is adapter


def test_chat_flows_get_the_repo_and_the_adapter(monkeypatch):
    adapter, repo = object(), object()
    monkeypatch.setattr(factories, "_cached", _fake_cached(adapter))
    flow = factories.create_flow(
        "chat", session=Session(id="c1", task="t"), llm=MagicMock(), tools=None, state_repo=repo
    )
    assert flow._state_repo is repo
    assert flow._get_persistence_adapter() is adapter


def test_sub_agent_flows_get_the_adapter(monkeypatch):
    adapter = object()
    monkeypatch.setattr(
        factories, "_cached", lambda key: adapter if key == "session_persistence" else object()
    )
    flow = factories._get_flow_factory(MagicMock())(Session(id="s1", task="t"))
    assert flow._get_persistence_adapter() is adapter


def test_flows_built_without_a_mediator_get_the_containers(monkeypatch):
    # Gateways and /api/webhook/run passed none, so PlanningState refused to
    # plan ("requires a Mediator") on every message (F43).
    from weebot.application.cqrs.mediator import Mediator

    mediator = object()
    monkeypatch.setattr(factories, "_cached", lambda key: mediator if key is Mediator else None)
    for kind in ("plan_act", "chat"):
        flow = factories.create_flow(
            kind, session=Session(id=kind, task="t"), llm=MagicMock(), tools=ToolCollection()
        )
        assert flow._mediator is mediator, kind


async def test_build_tools_without_an_llm_still_wires_sub_agent_tools(monkeypatch):
    # Web sessions, the webhook and the gateways call build_tools() with no
    # llm_port, so debate/swarm/dispatch got flow_factory=None and errored (F48).
    from weebot.application.ports.llm_port import LLMPort

    llm = MagicMock(spec=LLMPort)
    real = factories._cached
    monkeypatch.setattr(factories, "_cached", lambda key: llm if key is LLMPort else real(key))
    tools = await factories.build_tools(role="admin")
    debate = tools.get_tool("debate")
    assert debate is not None and debate._flow_factory is not None


def test_flows_built_without_a_bus_get_the_containers(monkeypatch):
    # Gateway and webhook flows passed no event bus: no domain events, and the
    # web UI never saw their progress (F56).
    from weebot.application.ports.event_bus_port import EventBusPort

    bus = object()
    monkeypatch.setattr(factories, "_cached", lambda key: bus if key is EventBusPort else None)
    flow = factories.create_flow(
        "plan_act", session=Session(id="g1", task="t"), llm=MagicMock(), tools=ToolCollection()
    )
    assert flow._event_bus is bus
