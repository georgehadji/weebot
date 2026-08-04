"""Integration test for the T0.4 wiring: bus → broadcaster → WebSocket.

Prior to this wiring, ``WebSocketEventBroadcaster`` was defined but never
instantiated or subscribed anywhere (see mission_center_ui_implementation_plan.md
RC-1) — events published on the bus never reached a connected browser.
This test builds the same three collaborators main.py's lifespan wires
together (AsyncEventBus, WebSocketEventBroadcaster, ConnectionManager) and
proves:

  1. An event published with session_id=X reaches a socket connected to
     /ws/sessions/X.
  2. It does NOT reach a socket connected to a different session.
  3. A session-scoped event does NOT reach the global (session-less) socket.

For (2) and (3), ``WebSocketTestSession.receive`` has no timeout and blocks
forever on an empty queue — there is no way to prove "nothing arrived"
by racing a bounded wait against it without leaking a thread stuck in a
blocking call (this was tried and deadlocks pytest on teardown). Instead
each test publishes a second, distinguishable "sentinel" event addressed
to the socket under test *after* the cross-session event, then asserts
that socket's very next message is the sentinel. Since delivery preserves
publish order, the sentinel arriving first proves the earlier event was
never enqueued for that socket.

A minimal FastAPI app is used instead of the full ``create_app()`` so the
test isolates the wiring itself from auth/lifespan/scheduler concerns
already covered by other tests.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from weebot.domain.models.event import MessageEvent
from weebot.infrastructure.event_bus import AsyncEventBus
from weebot.interfaces.web.event_broadcaster import WebSocketEventBroadcaster
from weebot.interfaces.web.websocket import ConnectionManager


def _build_test_app(manager: ConnectionManager) -> FastAPI:
    """Minimal app exposing the same two WS routes main.py wires, no auth."""
    app = FastAPI()

    @app.websocket("/ws")
    async def ws_global(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(websocket)

    @app.websocket("/ws/sessions/{session_id}")
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await manager.connect(websocket, session_id)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await manager.disconnect(websocket, session_id)

    return app


@pytest.fixture
def wired_app():
    """A bus + broadcaster + manager wired exactly as main.py's lifespan does."""
    manager = ConnectionManager()
    bus = AsyncEventBus()
    broadcaster = WebSocketEventBroadcaster(manager)
    bus.subscribe(broadcaster.publish)
    app = _build_test_app(manager)
    return app, bus


def test_session_scoped_event_reaches_matching_session_socket(wired_app):
    app, bus = wired_app
    client = TestClient(app)

    with client.websocket_connect("/ws/sessions/session-a") as ws:
        asyncio.run(bus.publish(MessageEvent(role="assistant", message="hi a", session_id="session-a")))
        received = ws.receive_json()

    assert received["type"] == "message"
    assert received["message"] == "hi a"
    assert received["session_id"] == "session-a"


def test_session_scoped_event_does_not_reach_other_session_socket(wired_app):
    app, bus = wired_app
    client = TestClient(app)

    with client.websocket_connect("/ws/sessions/session-a") as ws_a, \
         client.websocket_connect("/ws/sessions/session-b") as ws_b:
        asyncio.run(bus.publish(MessageEvent(role="assistant", message="only a", session_id="session-a")))
        asyncio.run(bus.publish(MessageEvent(role="assistant", message="sentinel-b", session_id="session-b")))

        received_a = ws_a.receive_json()
        assert received_a["session_id"] == "session-a"

        # If the session-a event had leaked to session-b's socket, it would
        # have been delivered before the sentinel (publish order preserved).
        received_b = ws_b.receive_json()
        assert received_b["message"] == "sentinel-b"
        assert received_b["session_id"] == "session-b"


def test_session_scoped_event_does_not_reach_global_socket(wired_app):
    app, bus = wired_app
    client = TestClient(app)

    with client.websocket_connect("/ws/sessions/session-a") as ws_a, \
         client.websocket_connect("/ws") as ws_global:
        asyncio.run(bus.publish(MessageEvent(role="assistant", message="scoped", session_id="session-a")))
        # No session_id → the broadcaster routes this to broadcast_global().
        asyncio.run(bus.publish(MessageEvent(role="assistant", message="sentinel-global")))

        ws_a.receive_json()  # the session socket gets the scoped event

        received_global = ws_global.receive_json()
        assert received_global["message"] == "sentinel-global"
