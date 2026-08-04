"""Regression test: POST /sessions/{id}/run must accept a fresh session.

Prior to this fix, run_session checked
``session.status not in (SessionStatus.IDLE, SessionStatus.FAILED)`` —
but SessionStatus has no IDLE member (only PENDING/RUNNING/WAITING/
COMPLETED/FAILED; a fresh Session defaults to PENDING). Every call to
this endpoint raised AttributeError before reaching the actual check,
which is exactly what the frontend calls immediately after creating a
session (sessions/new/page.tsx → api.sessions.run(session.id)) — so
starting any session from the UI was completely broken.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.domain.models.session import SessionStatus
from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.routers.sessions import router as sessions_router


def _build_app(monkeypatch, session_status: SessionStatus, has_prompt: bool = True):
    app = FastAPI()
    app.include_router(sessions_router)
    app.dependency_overrides[require_mutation_identity] = lambda: None

    fake_session = MagicMock()
    fake_session.id = "sess-1"
    fake_session.user_id = "anonymous"
    fake_session.agent_id = "weebot-web"
    fake_session.title = None
    fake_session.status = session_status
    fake_session.context = {"last_prompt": "do the thing"} if has_prompt else {}
    fake_session.created_at = "2026-01-01T00:00:00Z"
    fake_session.updated_at = "2026-01-01T00:00:00Z"
    fake_session.events = []

    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=fake_session)

    task_runner = MagicMock()
    task_runner.create_plan_act_factory = MagicMock(return_value=lambda session: MagicMock())
    task_runner.start_session = AsyncMock(return_value=fake_session)

    def _get(port_type):
        name = getattr(port_type, "__name__", "")
        if name in ("TaskRunner", "TaskRunnerPort"):
            return task_runner
        if name == "StateRepositoryPort":
            return state_repo
        # LLMPort / EventBusPort / SteeringPort — unused by the status check itself.
        return MagicMock()

    container = MagicMock()
    container.get = MagicMock(side_effect=_get)
    app.state.container = container

    async def _fake_build_tools(role):
        tools = MagicMock()
        tools.teardown = AsyncMock()
        return tools

    monkeypatch.setattr("weebot.interfaces.factories.build_tools", _fake_build_tools)

    return app


def test_run_pending_session_does_not_raise_attribute_error(monkeypatch):
    """The bug: SessionStatus.IDLE doesn't exist — PENDING is the real default."""
    app = _build_app(monkeypatch, SessionStatus.PENDING)
    client = TestClient(app)

    response = client.post("/sessions/sess-1/run")

    assert response.status_code not in (500, 404)


def test_run_failed_session_is_also_accepted(monkeypatch):
    app = _build_app(monkeypatch, SessionStatus.FAILED)
    client = TestClient(app)

    response = client.post("/sessions/sess-1/run")

    assert response.status_code not in (500, 404)


def test_run_already_running_session_rejected_with_409(monkeypatch):
    app = _build_app(monkeypatch, SessionStatus.RUNNING)
    client = TestClient(app)

    response = client.post("/sessions/sess-1/run")

    assert response.status_code == 409
