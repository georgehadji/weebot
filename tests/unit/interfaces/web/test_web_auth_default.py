"""Tests for C1 (FailClosedMiddleware) and M13 (require_mutation_identity)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from weebot.interfaces.web.auth import require_mutation_identity
from weebot.interfaces.web.main import create_app

# ── helpers ─────────────────────────────────────────────────────────────────


def _mock_settings_class(**overrides):
    """Build a fake WeebotSettings class for monkeypatching."""

    class _MockSettings:
        def __init__(self, **kw):
            values = {
                "weebot_api_key": None,
                "web_require_auth": True,
                "web_host": "127.0.0.1",
                "webhook_api_key": None,
                "webhook_allow_exec_tools": False,
            }
            values.update(overrides)
            values.update(kw)
            for k, v in values.items():
                setattr(self, k, v)

    return _MockSettings


@asynccontextmanager
async def _noop_lifespan(app):
    """No-op lifespan so TestClient skips heavy startup/shutdown."""
    yield


def _create_app_with_mocks(monkeypatch, **settings):
    """Create app with patched settings/lifespan and a mock DI container."""
    monkeypatch.setattr("weebot.config.settings.WeebotSettings", _mock_settings_class(**settings))
    monkeypatch.setattr("weebot.interfaces.web.main.lifespan", _noop_lifespan)
    app = create_app()

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sessions = AsyncMock(return_value=[])
    mock_state_repo.count_sessions = AsyncMock(return_value=0)
    mock_container = MagicMock()
    mock_container.get = MagicMock(return_value=mock_state_repo)
    app.state.container = mock_container

    return app


def _wrap_app(app, host: str, port: int):
    """ASGI wrapper that overrides scope['client'] for IP simulation."""

    async def wrapper(scope, receive, send):
        scope["client"] = (host, port)
        await app(scope, receive, send)

    return wrapper


# ── tests ───────────────────────────────────────────────────────────────────


class TestFailClosedMiddleware:
    def test_fail_closed_remote_no_key(self, monkeypatch):
        app = _create_app_with_mocks(monkeypatch, weebot_api_key=None, web_require_auth=True)
        client = TestClient(_wrap_app(app, "10.0.0.5", 1234))
        response = client.get("/api/sessions")
        assert response.status_code == 503
        assert response.headers.get("X-Error-Code") == "AUTH_REQUIRED"

    def test_fail_closed_loopback_no_key(self, monkeypatch):
        app = _create_app_with_mocks(monkeypatch, weebot_api_key=None, web_require_auth=True)
        client = TestClient(_wrap_app(app, "127.0.0.1", 1234))
        response = client.get("/api/sessions")
        assert response.status_code in (200, 404)
        assert response.status_code != 503

    def test_fail_closed_health_always_open(self, monkeypatch):
        app = _create_app_with_mocks(monkeypatch, weebot_api_key=None, web_require_auth=True)
        client = TestClient(_wrap_app(app, "10.0.0.5", 1234))
        response = client.get("/api/health")
        assert response.status_code == 200


class TestAPIKeyMiddleware:
    def test_api_key_wrong_key(self, monkeypatch):
        app = _create_app_with_mocks(monkeypatch, weebot_api_key="secret")
        client = TestClient(app)
        response = client.get("/api/sessions", headers={"X-API-Key": "wrong"})
        assert response.status_code == 401
        assert response.headers.get("X-Error-Code") == "UNAUTHORIZED"

    def test_api_key_correct_key(self, monkeypatch):
        app = _create_app_with_mocks(monkeypatch, weebot_api_key="secret")
        client = TestClient(app)
        response = client.get("/api/sessions", headers={"X-API-Key": "secret"})
        assert response.status_code in (200, 404)

    def test_web_require_auth_false_open(self, monkeypatch):
        app = _create_app_with_mocks(monkeypatch, weebot_api_key=None, web_require_auth=False)
        client = TestClient(_wrap_app(app, "10.0.0.5", 1234))
        response = client.get("/api/sessions")
        assert response.status_code in (200, 404)
        assert response.status_code != 503


class TestRequireMutationIdentity:
    async def test_mutation_identity_remote_anonymous(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "10.0.0.5"

        with pytest.raises(Exception) as exc_info:
            await require_mutation_identity(request)
        assert exc_info.value.status_code == 403

    async def test_mutation_identity_loopback_allowed(self):
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        await require_mutation_identity(request)
