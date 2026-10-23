"""W5.3 (F28): gateways and the CLI AgentRunner take collaborators as arguments.

- `GatewayAdapter` built a whole `Container()` when given no `llm_port`. Every
  subclass already requires `llm`, so that branch only hid a caller bug; the
  parameter is now required.
- `AgentRunner` built a `Container()` in its constructor to fetch the
  `retention_agent`, on every CLI run and every container-built runner. It now
  receives it; the CLI entry points pass their own container's.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def no_container(monkeypatch):
    built: list[bool] = []

    def _record(*a, **k):
        built.append(True)
        raise AssertionError("built a Container")

    monkeypatch.setattr("weebot.application.di.Container", _record)
    return built


def test_a_gateway_needs_its_llm_port():
    from weebot.interfaces.gateways.base import GatewayAdapter

    param = inspect.signature(GatewayAdapter.__init__).parameters["llm_port"]
    assert param.default is inspect.Parameter.empty


def test_agent_runner_keeps_the_retention_agent_it_is_given(no_container):
    from weebot.interfaces.cli.agent_runner import AgentRunner

    agent = object()
    runner = AgentRunner(llm=MagicMock(), state_repo=AsyncMock(), retention_agent=agent)
    assert runner._retention_agent is agent and no_container == []


def test_agent_runner_without_one_builds_no_container(no_container):
    from weebot.interfaces.cli.agent_runner import AgentRunner

    runner = AgentRunner(llm=MagicMock(), state_repo=AsyncMock())
    assert runner._retention_agent is None and no_container == []


def test_the_container_hands_its_retention_agent_to_the_runner(monkeypatch):
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    agent = object()
    real = c._maybe_get_str
    monkeypatch.setattr(c, "_maybe_get_str", lambda k: agent if k == "retention_agent" else real(k))
    assert c.build_agent_runner(use_rich=False)._retention_agent is agent
