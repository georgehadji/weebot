"""A17: the UI sent the API key as ?token=, and uvicorn logs the query string.

The key now travels in the Sec-WebSocket-Protocol header as `bearer.<key>`, next to the
marker `weebot.v1`; the server echoes the marker, never the key. ?token= still works for one
release (decision D2) and logs a deprecation warning.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

KEY = "sekret-key-for-test"


@pytest.fixture
def client(monkeypatch):
    from weebot.config import settings as mod
    from weebot.interfaces.web.routers.behavior_router import router

    monkeypatch.setattr(mod.get_settings(), "weebot_api_key", KEY, raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("203.0.113.9", 50000))


def test_the_key_in_the_subprotocol_authenticates_and_the_marker_is_echoed(client):
    with client.websocket_connect(
        "/behavior/ws", subprotocols=["weebot.v1", f"bearer.{KEY}"]
    ) as ws:
        assert ws.accepted_subprotocol == "weebot.v1"
        assert ws.receive_json()["type"] == "connected"


def test_a_wrong_key_in_the_subprotocol_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/behavior/ws", subprotocols=["weebot.v1", "bearer.nope"]):
            pass
    assert refused.value.code == 4001


def test_a_client_that_offers_only_the_bearer_protocol_still_connects(client):
    with client.websocket_connect("/behavior/ws", subprotocols=[f"bearer.{KEY}"]) as ws:
        assert ws.accepted_subprotocol == f"bearer.{KEY}"


def test_the_query_token_still_works_and_warns(client, caplog):
    with caplog.at_level(logging.WARNING):
        with client.websocket_connect(f"/behavior/ws?token={KEY}") as ws:
            assert ws.receive_json()["type"] == "connected"
    assert any("deprecated" in r.getMessage().lower() for r in caplog.records)
