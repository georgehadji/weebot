"""Regression test: broadcast_to_session KeyError when session removed mid-broadcast.

BUG: ConnectionManager.broadcast_to_session() acquired the lock twice — once
to copy connections, once to clean up disconnected clients.  If disconnect()
removed the last connection (and deleted the session key) between those two
lock acquisitions, the cleanup loop raised KeyError on the missing key.

FIX: Guard the cleanup loop with ``if session_id in self._connections``.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from weebot.interfaces.web.websocket import ConnectionManager


class FakeWebSocket:
    """Minimal fake that tracks calls to send_text and records disconnects."""

    def __init__(self, fail_on_send: bool = False):
        self.sent: list[str] = []
        self._fail = fail_on_send
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self._fail:
            raise ConnectionError("simulated send failure")
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_broadcast_cleanup_guards_against_missing_session():
    """If the session key is removed between copy and cleanup loops,
    broadcast_to_session must not raise KeyError.

    We simulate this by creating a connection that will fail on send
    (triggering cleanup), then removing the session key before the
    cleanup phase.  Since we can't patch built-in set.discard, we
    inject the session removal by patching the ConnectionManager's
    own send_text for the failing websocket to also remove the key.
    """
    mgr = ConnectionManager()

    removal_done = False

    class RaceWebSocket(FakeWebSocket):
        async def send_text(self, data: str) -> None:
            nonlocal removal_done
            if not removal_done:
                # Simulate a racing disconnect() removing the session
                async with mgr._connections_lock:
                    mgr._connections.pop("s1", None)
                removal_done = True
            raise ConnectionError("simulated send failure")

    ws = RaceWebSocket()
    await mgr.connect(ws, "s1")

    # broadcast_to_session will: copy → send (fails + removes session) → cleanup
    # The cleanup must not KeyError on the missing "s1" key.
    await mgr.broadcast_to_session("s1", {"event": "test"})


@pytest.mark.asyncio
async def test_broadcast_unknown_session_returns_early():
    """broadcast_to_session for unknown session returns without error."""
    mgr = ConnectionManager()
    await mgr.broadcast_to_session("nonexistent", {"x": 1})


@pytest.mark.asyncio
async def test_broadcast_to_empty_connections_after_disconnect():
    """After the last connection disconnects, broadcasting returns early
    without error (session key already deleted by disconnect)."""
    mgr = ConnectionManager()
    ws = FakeWebSocket()
    await mgr.connect(ws, "s1")
    await mgr.disconnect(ws, "s1")

    # Session "s1" should no longer exist
    await mgr.broadcast_to_session("s1", {"event": "test"})
    # No exception = pass
