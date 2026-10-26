"""W5.2 (F28): Mediator dispatch kind, injected tracer, surfaced tool-less fallback.

- A query sent through `send` (or a command through `query`) used to fail as
  "no handler registered", which is how F22 hid as a plain 500. Now the wrong
  kind raises TypeError naming the right method.
- The tracer was resolved by building and configuring a whole `Container()`
  inside the Mediator on first use. It is now a constructor argument, with a
  no-op default.
- When `build_mediator` cannot build the admin tool set, every step runs with
  no tools. That was one warning line; it now also marks the mediator
  degraded, and `/health` reports it.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.application.cqrs.commands import CreatePlanCommand
from weebot.application.cqrs.mediator import Mediator
from weebot.application.cqrs.queries import GetCostSummaryQuery


async def test_send_rejects_a_query():
    with pytest.raises(TypeError, match="query"):
        await Mediator().send(GetCostSummaryQuery())


async def test_query_rejects_a_command():
    with pytest.raises(TypeError, match="send"):
        await Mediator().query(CreatePlanCommand(session_id="s1", prompt="p"))


async def test_the_injected_tracer_wraps_each_request():
    names = []

    class _Tracer:
        def start_as_current_span(self, name):
            names.append(name)
            return nullcontext(MagicMock())

    mediator = Mediator(tracer=_Tracer())
    await mediator.query(GetCostSummaryQuery())
    assert names == ["query.GetCostSummaryQuery"]


async def test_no_tracer_builds_no_container(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("Mediator built a Container to find its tracer")

    monkeypatch.setattr("weebot.application.di.Container", _boom)
    result = await Mediator().query(GetCostSummaryQuery())
    assert not result.success  # no handler registered, but no Container either


def test_a_tool_less_mediator_is_marked_degraded(monkeypatch, caplog):
    from weebot.application.di import Container
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.services.tool_registry import RoleBasedToolRegistry

    def _fail(self, *a, **k):
        raise RuntimeError("tool wiring broke")

    monkeypatch.setattr(RoleBasedToolRegistry, "create_tool_collection", _fail)
    c = Container()
    c.configure_defaults()
    real_maybe_get = c._maybe_get
    monkeypatch.setattr(
        c, "_maybe_get", lambda key: MagicMock() if key is LLMPort else real_maybe_get(key)
    )
    with caplog.at_level(logging.WARNING):
        mediator = c.build_mediator()
    assert "tool wiring broke" in mediator.degraded["tools"]
    assert "tool-less" in caplog.text


def test_health_reports_a_tool_less_mediator():
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.web.routers import health

    mediator = Mediator()
    mediator.degraded["tools"] = "RuntimeError: tool wiring broke"

    class _Repo:
        async def list_sessions(self, *a, **k):
            return []

    class _AppContainer:
        def get(self, key):
            return {Mediator: mediator, StateRepositoryPort: _Repo()}[key]

    app = FastAPI()
    app.state.container = _AppContainer()
    app.include_router(health.router)
    path = next(r.path for r in health.router.routes if r.name == "health_check")
    body = TestClient(app).get(path).json()
    tools = [c for c in body["components"] if c["name"] == "agent_tools"]
    assert tools and tools[0]["status"] == "degraded"
    assert body["status"] != "healthy"


def test_status_passes_its_state_repo_to_the_health_check():
    """/health/status called health_check() with no arguments, so the state
    repo was FastAPI's Depends marker and the database always read unhealthy."""
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.web.routers import health

    class _Repo:
        async def list_sessions(self, *a, **k):
            return []

    class _AppContainer:
        def get(self, key):
            return {Mediator: Mediator(), StateRepositoryPort: _Repo()}[key]

    app = FastAPI()
    app.state.container = _AppContainer()
    app.include_router(health.router)
    body = TestClient(app).get("/health/status").json()
    database = [c for c in body["components"] if c["name"] == "database"]
    assert database and database[0]["status"] == "healthy"
