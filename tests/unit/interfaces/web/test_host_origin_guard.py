"""The web app refuses a foreign Host from a loopback peer and a foreign WebSocket Origin.

With no API key a loopback peer counts as the operator. A hostile page reaches that peer in two
ways: DNS rebinding (its own domain re-resolves to 127.0.0.1, so the browser sends the request
with ``Host: evil.test``) and a cross-site WebSocket (CORS does not apply to a handshake).
``HostGuardMiddleware`` closes both for every route, so a new WebSocket route cannot forget it.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import APIWebSocketRoute
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from weebot.interfaces.web.main import create_app

GUARD_CLOSE_CODE = 4403  # 4003 is already the routes' own auth close


class _Settings:
    def __init__(self, **kw):
        values = {
            "weebot_api_key": None,
            "web_require_auth": True,
            "web_host": "127.0.0.1",
            "webhook_api_key": None,
            "webhook_allow_exec_tools": False,
        }
        values.update(kw)
        for k, v in values.items():
            setattr(self, k, v)


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("weebot.config.settings.WeebotSettings", _Settings)
    monkeypatch.setattr("weebot.interfaces.web.main.lifespan", _noop_lifespan)
    monkeypatch.delenv("WEEBOT_ALLOWED_HOSTS", raising=False)
    application = create_app()
    repo = AsyncMock()
    repo.list_sessions = AsyncMock(return_value=[])
    repo.count_sessions = AsyncMock(return_value=0)
    container = MagicMock()
    container.get = MagicMock(return_value=repo)
    application.state.container = container
    return application


def _from_peer(app, host: str, port: int = 50000):
    """ASGI wrapper that sets the peer address, as a socket would."""

    async def wrapper(scope, receive, send):
        scope["client"] = (host, port)
        await app(scope, receive, send)

    return wrapper


def _client(app, peer: str, host_header: str) -> TestClient:
    return TestClient(
        _from_peer(app, peer), base_url=f"http://{host_header}", raise_server_exceptions=False
    )


# ── Host ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("host", ["evil.test", "evil.test:8000", "localhost.evil.test"])
def test_a_loopback_peer_with_a_foreign_host_is_refused(app, host):
    response = _client(app, "127.0.0.1", host).get("/api/sessions")
    assert response.status_code == 421


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
def test_a_loopback_peer_with_a_local_host_passes(app, host):
    response = _client(app, "127.0.0.1", host).get("/api/sessions")
    assert response.status_code != 421


def test_health_is_not_exempt_from_the_host_check(app):
    """DNS rebinding also reads health; the check is not path based."""
    response = _client(app, "127.0.0.1", "evil.test").get("/api/health")
    assert response.status_code == 421


def test_a_remote_peer_is_not_judged_by_host(app):
    """A remote caller has no loopback trust to abuse; the key check answers instead."""
    response = _client(app, "10.0.0.5", "weebot.lan:8000").get("/api/sessions")
    assert response.status_code != 421


def test_a_configured_host_is_allowed(app, monkeypatch):
    monkeypatch.setenv("WEEBOT_ALLOWED_HOSTS", "weebot.lan")
    response = _client(app, "127.0.0.1", "weebot.lan:8000").get("/api/sessions")
    assert response.status_code != 421


# ── WebSocket Origin ────────────────────────────────────────────────────────


def _websocket_paths(app) -> list[str]:
    paths = [
        route.path
        for route in app.routes
        if isinstance(route, (WebSocketRoute, APIWebSocketRoute))
    ]
    return [re.sub(r"\{[^}]+\}", "x", p) for p in paths]


def test_the_app_has_websocket_routes_to_guard(app):
    """Guards the guard: an empty list would make the loop below vacuous."""
    assert len(_websocket_paths(app)) >= 2


def test_every_websocket_route_refuses_a_foreign_origin(app):
    client = _client(app, "127.0.0.1", "localhost:8000")
    for path in _websocket_paths(app):
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(
                path, headers={"host": "localhost:8000", "origin": "http://evil.test"}
            ):
                pass
        assert refused.value.code == GUARD_CLOSE_CODE, path


def test_a_foreign_origin_is_refused_for_a_remote_peer_too(app):
    client = _client(app, "10.0.0.5", "weebot.lan:8000")
    path = _websocket_paths(app)[0]
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(
            path, headers={"host": "weebot.lan:8000", "origin": "http://evil.test"}
        ):
            pass
    assert refused.value.code == GUARD_CLOSE_CODE


@pytest.mark.parametrize("origin", [None, "http://localhost:3000", "http://127.0.0.1:3000"])
def test_websocket_without_origin_or_with_the_ui_origin_is_not_refused_by_the_guard(
    app, origin
):
    client = _client(app, "127.0.0.1", "localhost:8000")
    headers = {"host": "localhost:8000"}
    if origin:
        headers["origin"] = origin
    for path in _websocket_paths(app):
        try:
            with client.websocket_connect(path, headers=headers):
                pass
        except WebSocketDisconnect as closed:
            assert closed.code != GUARD_CLOSE_CODE, path
        except Exception:  # the route itself may fail on a mocked container
            pass


def test_a_loopback_websocket_with_a_foreign_host_is_refused(app):
    client = _client(app, "127.0.0.1", "localhost:8000")
    path = _websocket_paths(app)[0]
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(path, headers={"host": "evil.test"}):
            pass
    assert refused.value.code == GUARD_CLOSE_CODE
