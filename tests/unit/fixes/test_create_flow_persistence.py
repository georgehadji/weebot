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
