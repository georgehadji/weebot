"""F22: ops_router passed queries to Mediator.send and built a Container per request.

`send` looks in the command table, finds no handler for a query type and
fails, so every ops endpoint returned 500 even with a working query handler
(the Plan panel's "Internal server error"). W7.1: the router sends queries
through `Mediator.query` and resolves the one container the app lifespan put
on `app.state`, via `Depends`.
"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.application.cqrs.mediator import Mediator
from weebot.application.cqrs.queries import (
    GetActiveSessionsQuery,
    GetCostSummaryQuery,
    GetPlanVisualizationQuery,
)
from weebot.application.ports.state_repo_port import StateRepositoryPort


class _Handler:
    def __init__(self, data):
        self.data = data
        self.seen = []

    async def handle(self, query):
        self.seen.append(query)
        return self.data


class _Tracer:
    def start_as_current_span(self, name):
        return nullcontext(MagicMock())


class _StateRepo:
    async def load_session(self, session_id):
        return SimpleNamespace(user_id=None) if session_id == "s1" else None


class _AppContainer:
    def __init__(self, mediator):
        self._by_key = {Mediator: mediator, StateRepositoryPort: _StateRepo()}

    def get(self, key):
        return self._by_key[key]


@pytest.fixture
def client(monkeypatch):
    def _no_per_request_container(*a, **k):
        raise AssertionError("ops_router built a Container per request")

    monkeypatch.setattr("weebot.application.di.Container", _no_per_request_container)
    from weebot.interfaces.web.routers import ops_router

    mediator = Mediator()
    mediator._tracer = _Tracer()
    handlers = {
        GetCostSummaryQuery: _Handler({"total_cost": 0.0}),
        GetActiveSessionsQuery: _Handler([{"session_id": "s1"}]),
        GetPlanVisualizationQuery: _Handler({"nodes": [], "edges": []}),
    }
    for qtype, handler in handlers.items():
        mediator.register_query_handler(qtype, handler)

    app = FastAPI()
    app.state.container = _AppContainer(mediator)
    app.include_router(ops_router.router)
    return TestClient(app), handlers


def test_cost_summary_endpoint_uses_the_query_handler(client):
    http, handlers = client
    response = http.get("/api/costs/summary?window_hours=6")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {"total_cost": 0.0}}
    assert handlers[GetCostSummaryQuery].seen[0].window_hours == 6


def test_active_sessions_endpoint_uses_the_query_handler(client):
    http, _ = client
    response = http.get("/api/sessions/active")
    assert response.status_code == 200
    assert response.json()["data"] == [{"session_id": "s1"}]


def test_plan_viz_endpoint_uses_the_query_handler(client):
    http, handlers = client
    response = http.get("/api/sessions/s1/plan-viz")
    assert response.status_code == 200
    assert response.json()["data"] == {"nodes": [], "edges": []}
    assert handlers[GetPlanVisualizationQuery].seen[0].session_id == "s1"


def test_plan_viz_for_an_unknown_session_is_404(client):
    http, _ = client
    assert http.get("/api/sessions/nope/plan-viz").status_code == 404
