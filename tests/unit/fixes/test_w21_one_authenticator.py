"""W2.1: one authenticator decides who a caller is, for HTTP, the middleware and sockets.

Found by the 2026-10-27 audit (A27, master plan track A6): auth was computed in four
places from different sources. The route dependencies resolved store-mode keys, but
the HTTP middleware compared only X-API-Key with the legacy key and every socket
compared only the legacy key, so a per-principal key got a 401 or a closed socket.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.unit.interfaces.web.test_auth_resolves_through_the_port import RAW, FakeKeys
from tests.unit.interfaces.web.test_web_auth_default import _create_app_with_mocks, _wrap_app
from weebot.interfaces.web import auth


@pytest.fixture
def store_mode(monkeypatch):
    monkeypatch.setenv("WEEBOT_AUTH_MODE", "store")


def _app(monkeypatch, **settings):
    app = _create_app_with_mocks(monkeypatch, **settings)
    app.state.api_key_store = FakeKeys()
    return app


def _socket(protocols: str):
    return SimpleNamespace(
        headers={"sec-websocket-protocol": protocols},
        scope={"type": "websocket"},
        query_params={},
        app=SimpleNamespace(state=SimpleNamespace(api_key_store=FakeKeys())),
        client=SimpleNamespace(host="203.0.113.9"),
    )


async def test_a_store_key_in_a_subprotocol_names_its_principal(store_mode):
    assert await auth.authenticate(_socket(f"weebot.v1, bearer.{RAW}")) == "alice"


async def test_an_unknown_key_is_refused(store_mode):
    assert await auth.authenticate(_socket("weebot.v1, bearer.wb_nobody")) is None


def test_the_middleware_lets_a_store_key_through(monkeypatch, store_mode):
    app = _app(monkeypatch, weebot_api_key="legacy-key")
    client = TestClient(_wrap_app(app, "203.0.113.9", 1234))
    assert client.get("/api/sessions", headers={"X-API-Key": RAW}).status_code != 401


def test_store_mode_without_a_legacy_key_admits_remote_store_keys(monkeypatch, store_mode):
    app = _app(monkeypatch, weebot_api_key=None, web_require_auth=True)
    client = TestClient(_wrap_app(app, "203.0.113.9", 1234))
    assert client.get("/api/sessions", headers={"X-API-Key": RAW}).status_code in (200, 404)
    assert client.get("/api/sessions").status_code == 401


def test_the_middleware_accepts_a_bearer_header(monkeypatch):
    app = _app(monkeypatch, weebot_api_key="legacy-key")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/sessions", headers={"Authorization": "Bearer legacy-key"})
    assert response.status_code in (200, 404)


def test_a_configured_key_still_refuses_a_keyless_loopback_caller(monkeypatch):
    app = _app(monkeypatch, weebot_api_key="legacy-key")
    client = TestClient(_wrap_app(app, "127.0.0.1", 1234))
    assert client.get("/api/sessions").status_code == 401


def test_a_store_key_opens_the_global_socket(monkeypatch, store_mode):
    client = TestClient(_app(monkeypatch, weebot_api_key=None, web_require_auth=True))
    with client.websocket_connect("/ws", subprotocols=["weebot.v1", f"bearer.{RAW}"]):
        pass


def test_a_socket_with_no_key_stays_closed_in_store_mode(monkeypatch, store_mode):
    client = TestClient(_app(monkeypatch, weebot_api_key=None, web_require_auth=True))
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()


async def test_a_request_verifies_its_key_once(store_mode):
    """The middleware and then the route both ask; the scrypt check runs once."""
    conn = _socket(f"bearer.{RAW}")
    keys = conn.app.state.api_key_store
    assert await auth.authenticate(conn) == await auth.authenticate(conn) == "alice"
    assert keys.touched == ["k1"]
