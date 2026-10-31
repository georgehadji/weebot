"""A06: the behavior WebSockets accepted any client when no API key was configured.

Now they follow the mutation rule: with no key, only a loopback client gets in.
The per-session socket also accepts the same three credential forms as the main one.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

PATHS = ["/behavior/ws", "/behavior/ws/session/s1"]


def _client(host: str = "testclient") -> TestClient:
    from weebot.interfaces.web.routers.behavior_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=(host, 50000))


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    from weebot.config import settings as mod

    def _set(key):
        s = mod.get_settings()
        monkeypatch.setattr(s, "weebot_api_key", key, raising=False)

    return _set


def _closed_with_4001(client, path, **kw) -> bool:
    try:
        with client.websocket_connect(path, **kw):
            return False
    except WebSocketDisconnect as exc:
        return exc.code == 4001


@pytest.mark.parametrize("path", PATHS)
def test_no_key_and_a_remote_client_is_refused(path, _settings):
    _settings(None)
    assert _closed_with_4001(_client("203.0.113.9"), path)


@pytest.mark.parametrize("path", PATHS)
def test_no_key_and_a_loopback_client_is_accepted(path, _settings):
    _settings(None)
    with _client("127.0.0.1").websocket_connect(path) as ws:
        assert ws.receive_json()["type"] == "connected"


@pytest.mark.parametrize("path", PATHS)
def test_a_wrong_token_is_refused_and_the_right_one_accepted(path, _settings):
    _settings("sekret-key-for-test")
    assert _closed_with_4001(_client(), path, subprotocols=["bearer.nope"])
    assert _closed_with_4001(_client(), path + "?token=sekret-key-for-test")  # D2: no ?token=
    with _client().websocket_connect(path, subprotocols=["bearer.sekret-key-for-test"]) as ws:
        assert ws.receive_json()["type"] == "connected"


@pytest.mark.parametrize("path", PATHS)
def test_the_bearer_header_is_accepted(path, _settings):
    _settings("sekret-key-for-test")
    headers = {"Authorization": "Bearer sekret-key-for-test"}
    with _client().websocket_connect(path, headers=headers) as ws:
        assert ws.receive_json()["type"] == "connected"
