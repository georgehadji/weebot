"""Tests for H2 webhook auth and tool role."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from weebot.interfaces.web.routers.webhook import require_webhook_auth


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


def _make_webhook_app(monkeypatch, **settings):
    """Build a minimal FastAPI app with the webhook router and a mock container."""
    monkeypatch.setattr(
        "weebot.config.settings.WeebotSettings",
        _mock_settings_class(**settings),
    )
    from weebot.interfaces.web.routers.webhook import router as webhook_router
    app = FastAPI()
    app.include_router(webhook_router)

    mock_state_repo = AsyncMock()
    mock_state_repo.load_session = AsyncMock(return_value=None)
    mock_container = MagicMock()
    mock_container.get = MagicMock(return_value=mock_state_repo)
    app.state.container = mock_container
    return app


# ── tests ───────────────────────────────────────────────────────────────────


class TestRequireWebhookAuth:
    async def test_webhook_no_key_remote_401(self, monkeypatch):
        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _mock_settings_class(webhook_api_key=None, weebot_api_key=None),
        )
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "10.0.0.5"

        with pytest.raises(HTTPException) as exc_info:
            await require_webhook_auth(request)
        assert exc_info.value.status_code == 401

    async def test_webhook_no_key_loopback_200(self, monkeypatch):
        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _mock_settings_class(webhook_api_key=None, weebot_api_key=None),
        )
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        await require_webhook_auth(request)

    async def test_webhook_webhook_key_wrong(self, monkeypatch):
        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _mock_settings_class(webhook_api_key="secret"),
        )
        request = MagicMock(spec=Request)
        request.headers = {"X-Webhook-Key": "wrong"}
        request.client = MagicMock()
        request.client.host = "10.0.0.5"

        with pytest.raises(HTTPException) as exc_info:
            await require_webhook_auth(request)
        assert exc_info.value.status_code == 401

    async def test_webhook_webhook_key_correct(self, monkeypatch):
        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _mock_settings_class(webhook_api_key="secret"),
        )
        request = MagicMock(spec=Request)
        request.headers = {"X-Webhook-Key": "secret"}
        request.client = MagicMock()
        request.client.host = "10.0.0.5"

        await require_webhook_auth(request)

    async def test_webhook_fallback_to_global_key(self, monkeypatch):
        monkeypatch.setattr(
            "weebot.config.settings.WeebotSettings",
            _mock_settings_class(webhook_api_key=None, weebot_api_key="global"),
        )
        request = MagicMock(spec=Request)
        request.headers = {"X-API-Key": "global"}
        request.client = MagicMock()
        request.client.host = "10.0.0.5"

        await require_webhook_auth(request)


class TestWebhookToolRole:
    def test_webhook_uses_webhook_role_by_default(self, monkeypatch):
        app = _make_webhook_app(
            monkeypatch, webhook_api_key="secret", webhook_allow_exec_tools=False
        )

        mock_tools = MagicMock()
        mock_tools.teardown = AsyncMock()

        async def _mock_run(text: str):
            return
            yield

        mock_flow = MagicMock()
        mock_flow.run = _mock_run
        mock_flow.is_done = MagicMock(return_value=True)

        with patch(
            "weebot.interfaces.web.routers.webhook.build_tools",
            new=AsyncMock(return_value=mock_tools),
        ) as mock_build_tools:
            with patch(
                "weebot.interfaces.web.routers.webhook.create_flow",
                return_value=mock_flow,
            ):
                client = TestClient(app)
                response = client.post(
                    "/api/webhook/run",
                    json={"text": "hello"},
                    headers={"X-Webhook-Key": "secret"},
                )
                assert response.status_code == 200
                mock_build_tools.assert_awaited_once_with(role="webhook")

    def test_webhook_uses_admin_role_when_exec_enabled(self, monkeypatch):
        app = _make_webhook_app(
            monkeypatch, webhook_api_key="secret", webhook_allow_exec_tools=True
        )

        mock_tools = MagicMock()
        mock_tools.teardown = AsyncMock()

        async def _mock_run(text: str):
            return
            yield

        mock_flow = MagicMock()
        mock_flow.run = _mock_run
        mock_flow.is_done = MagicMock(return_value=True)

        with patch(
            "weebot.interfaces.web.routers.webhook.build_tools",
            new=AsyncMock(return_value=mock_tools),
        ) as mock_build_tools:
            with patch(
                "weebot.interfaces.web.routers.webhook.create_flow",
                return_value=mock_flow,
            ):
                client = TestClient(app)
                response = client.post(
                    "/api/webhook/run",
                    json={"text": "hello"},
                    headers={"X-Webhook-Key": "secret"},
                )
                assert response.status_code == 200
                mock_build_tools.assert_awaited_once_with(role="admin")
