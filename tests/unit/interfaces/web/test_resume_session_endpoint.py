"""POST /sessions/{id}/resume must actually resume the flow (found in plan B2c).

It stored the answer and set RUNNING, the same no-op the composer's /input
WAITING strategy had, so a client using this endpoint left the session
RUNNING with nothing running. It now goes through the same dispatch as /input.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.routers.sessions import router as sessions_router


def _build_app(monkeypatch, status: SessionStatus):
    app = FastAPI()
    app.include_router(sessions_router)
    app.dependency_overrides[require_mutation_identity] = lambda: None

    session = Session(id="sess-1", user_id="anonymous", agent_id="weebot-web", status=status)
    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=session)

    task_runner = MagicMock()
    task_runner.create_plan_act_factory = MagicMock(return_value=lambda s: MagicMock())
    task_runner.resume_session = AsyncMock(
        side_effect=lambda sid, answer, f, **_kw: session.add_user_message(answer).set_status(
            SessionStatus.RUNNING
        )
    )

    def _get(port_type):
        name = getattr(port_type, "__name__", "")
        if name in ("TaskRunner", "TaskRunnerPort"):
            return task_runner
        if name == "StateRepositoryPort":
            return state_repo
        return MagicMock()

    container = MagicMock()
    container.get = MagicMock(side_effect=_get)
    app.state.container = container

    async def _fake_build_tools(role):
        tools = MagicMock()
        tools.teardown = AsyncMock()
        return tools

    monkeypatch.setattr("weebot.interfaces.factories.build_tools", _fake_build_tools)
    return app, task_runner


def test_resume_runs_the_flow_with_the_answer(monkeypatch):
    app, task_runner = _build_app(monkeypatch, SessionStatus.WAITING)
    response = TestClient(app).post("/sessions/sess-1/resume", json={"answer": "approve"})
    assert response.status_code == 200
    task_runner.resume_session.assert_awaited_once()
    assert task_runner.resume_session.await_args.args[:2] == ("sess-1", "approve")


def test_resume_of_a_session_that_is_not_waiting_is_refused(monkeypatch):
    app, task_runner = _build_app(monkeypatch, SessionStatus.RUNNING)
    response = TestClient(app).post("/sessions/sess-1/resume", json={"answer": "approve"})
    assert response.status_code == 400
    task_runner.resume_session.assert_not_awaited()
