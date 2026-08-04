"""Tests for POST /sessions/{id}/steer (T1.4).

Verifies:
  1. Steering a RUNNING session calls SteeringPort.send(session_id, text).
  2. Steering a non-RUNNING session (e.g. WAITING) is rejected with 409 —
     steering is a running-flow concept, distinct from /resume.
  3. A missing session returns 404.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from weebot.application.ports.steering_port import SteeringPort
from weebot.domain.models.session import SessionStatus
from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.routers.sessions import router as sessions_router


def _build_app(session_status: SessionStatus, session_found: bool = True):
    app = FastAPI()
    app.include_router(sessions_router)
    app.dependency_overrides[require_mutation_identity] = lambda: None

    fake_session = MagicMock()
    fake_session.user_id = "anonymous"
    fake_session.status = session_status

    state_repo = AsyncMock()
    state_repo.load_session = AsyncMock(return_value=fake_session if session_found else None)

    steering = AsyncMock(spec=SteeringPort)

    container = MagicMock()
    container.get = MagicMock(side_effect=lambda port: steering if port is SteeringPort else state_repo)

    app.state.container = container
    return app, steering


def test_steer_running_session_delivers_message():
    app, steering = _build_app(SessionStatus.RUNNING)
    client = TestClient(app)

    response = client.post("/sessions/sess-1/steer", json={"answer": "focus on the tests"})

    assert response.status_code == 200
    steering.send.assert_awaited_once_with("sess-1", "focus on the tests")


def test_steer_non_running_session_rejected():
    app, steering = _build_app(SessionStatus.WAITING)
    client = TestClient(app)

    response = client.post("/sessions/sess-1/steer", json={"answer": "hello"})

    assert response.status_code == 409
    steering.send.assert_not_awaited()


def test_steer_missing_session_returns_404():
    app, steering = _build_app(SessionStatus.RUNNING, session_found=False)
    client = TestClient(app)

    response = client.post("/sessions/sess-missing/steer", json={"answer": "hello"})

    assert response.status_code == 404
