"""Presence frames went to every connected session rail (found in the D10 fix, 2026-10-31).

A SessionPresenceEvent rides the global /ws channel so that a rail sees status changes of
sessions it is not subscribed to. The global channel had no notion of who was listening, so
every rail received every user's session ids, titles and statuses. The frame now names the
session's owner, /ws remembers each client's principal, and the frame goes only to its
owner's connections (unless ownership enforcement is off, or the session has no owner).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from weebot.domain.models.event import SessionPresenceEvent
from weebot.domain.models.session import Session


class _Ws:
    def __init__(self):
        self.headers = {}
        self.scope = {"type": "websocket", "headers": []}
        self.sent: list[dict] = []

    async def accept(self, subprotocol=None):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))


@pytest.mark.asyncio
async def test_the_global_channel_can_address_one_principal():
    from weebot.interfaces.web.websocket import ConnectionManager

    manager = ConnectionManager()
    alice, bob, legacy = _Ws(), _Ws(), _Ws()
    await manager.connect(alice, principal="alice")
    await manager.connect(bob, principal="bob")
    await manager.connect(legacy)
    await manager.broadcast_global({"n": 1}, only_principal="alice")
    await manager.broadcast_global({"n": 2})
    assert [m["n"] for m in alice.sent] == [1, 2]
    assert [m["n"] for m in bob.sent] == [2]
    assert [m["n"] for m in legacy.sent] == [2]


@pytest.mark.asyncio
@pytest.mark.parametrize("enforce,owner,expected", [
    ("true", "alice", "alice"),
    ("false", "alice", None),
    ("true", "", None),  # a legacy session with no owner stays visible to all
])
async def test_a_presence_frame_goes_to_its_owner(monkeypatch, enforce, owner, expected):
    from weebot.interfaces.web.event_broadcaster import WebSocketEventBroadcaster

    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", enforce)
    manager = SimpleNamespace(broadcast_global=AsyncMock(), broadcast_to_session=AsyncMock())
    await WebSocketEventBroadcaster(manager).publish(
        SessionPresenceEvent(about_session_id="s1", status="running", owner_user_id=owner)
    )
    assert manager.broadcast_global.await_args.kwargs.get("only_principal") == expected


@pytest.mark.asyncio
async def test_the_task_runner_names_the_owner():
    from weebot.application.services.task_runner import TaskRunner

    bus = SimpleNamespace(publish=AsyncMock())
    await TaskRunner._publish_presence(
        SimpleNamespace(_event_bus=bus), Session(id="s1", user_id="alice")
    )
    assert bus.publish.await_args.args[0].owner_user_id == "alice"
