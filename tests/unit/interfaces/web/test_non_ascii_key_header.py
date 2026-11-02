"""A non-ASCII API key header is a 401, not a 500.

``hmac.compare_digest`` raised ``TypeError`` on a latin-1 decoded header such as "é", so the
request died with a 500 and a traceback, and the failure was never counted by the throttle
(which only counts 401 and 403). Covers the legacy-key path in ``auth.py`` and the webhook key
check.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from weebot.interfaces.web.main import create_app

NON_ASCII = b"\xe9"


class _Settings:
    def __init__(self, **kw):
        values = {
            "weebot_api_key": "secret",
            "web_require_auth": True,
            "web_host": "127.0.0.1",
            "webhook_api_key": "hook-secret",
            "webhook_allow_exec_tools": False,
        }
        values.update(kw)
        for k, v in values.items():
            setattr(self, k, v)


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("weebot.config.settings.WeebotSettings", _Settings)
    monkeypatch.setattr("weebot.interfaces.web.main.lifespan", _noop_lifespan)
    app = create_app()
    repo = AsyncMock()
    repo.list_sessions = AsyncMock(return_value=[])
    repo.count_sessions = AsyncMock(return_value=0)
    container = MagicMock()
    container.get = MagicMock(return_value=repo)
    app.state.container = container
    return TestClient(app, raise_server_exceptions=False)


def test_a_non_ascii_api_key_is_rejected_not_crashed(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/sessions", headers={"X-API-Key": NON_ASCII})
    assert response.status_code == 401


def test_a_non_ascii_webhook_key_is_rejected_not_crashed(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/webhook/run", headers={"X-API-Key": NON_ASCII}, json={"prompt": "hi"}
    )
    assert response.status_code in (401, 403)
