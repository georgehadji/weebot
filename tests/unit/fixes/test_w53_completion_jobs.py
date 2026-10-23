"""W5.3 (F28): the post-completion jobs take their collaborators as arguments.

CompletedState spawns a skill-gap job and a dream scan after every flow. Each
used to build and configure a whole `Container()` (catalog validation, LLM
adapters, a second event bus) to fetch one or two services. The flow now
carries `idea_gate`, `dreamer_agent` and `event_store`, `factories.create_flow`
fills them from its one cached container, and the jobs receive them.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from weebot.application.flows.states import completed

_GAPS = [{"step": "summarise a PDF", "score": 0.1}]


@pytest.fixture
def no_container(monkeypatch):
    built: list[bool] = []

    def _record(*a, **k):
        built.append(True)
        raise AssertionError("a completion job built a Container")

    monkeypatch.setattr("weebot.application.di.Container", _record)
    return built


class _Gate:
    def __init__(self):
        self.seen = []

    async def process(self, contracts):
        self.seen.extend(contracts)
        return []


async def test_skill_gap_job_uses_the_gate_it_is_given(monkeypatch, no_container):
    monkeypatch.setattr("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True)
    gate = _Gate()
    await completed._run_skill_gap_processing(_GAPS, "s1", idea_gate=gate)
    assert len(gate.seen) == 1 and no_container == []


async def test_skill_gap_job_without_a_gate_does_nothing(monkeypatch, no_container):
    monkeypatch.setattr("weebot.config.feature_flags.SKILL_GAP_TRIGGER_ENABLED", True)
    await completed._run_skill_gap_processing(_GAPS, "s1", idea_gate=None)
    assert no_container == []


async def test_dream_scan_uses_the_dreamer_and_store_it_is_given(no_container):
    class _Store:
        async def query_recent_events(self, **kw):
            return []

    class _Dreamer:
        called = False

        async def dream(self, **kw):
            _Dreamer.called = True
            return []

    await completed._run_dream_scan(dreamer=_Dreamer(), event_store=_Store(), idea_gate=None)
    assert _Dreamer.called and no_container == []


def test_create_flow_hands_the_flow_its_completion_collaborators(monkeypatch):
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session
    from weebot.interfaces import factories

    wanted = {"idea_gate": object(), "dreamer_agent": object()}
    store = object()

    def _fake_cached(key):
        from weebot.application.ports.event_store_port import EventStorePort

        if key is EventStorePort:
            return store
        return wanted.get(key)

    monkeypatch.setattr(factories, "_cached", _fake_cached)
    flow = factories.create_flow(
        "plan_act", session=Session(id="s1", task="t"), llm=MagicMock(), tools=ToolCollection()
    )
    assert flow._idea_gate is wanted["idea_gate"]
    assert flow._dreamer_agent is wanted["dreamer_agent"]
    assert flow._event_store is store
