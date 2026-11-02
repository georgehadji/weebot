"""W2-4 (UI defect hunt, 2026-10-31): the SSE "N event(s) dropped" notice carried no id.

The UI dedupes events by id, so every drop notice after the first one was discarded. The
notice now has its own id, a timestamp, and the session of the event it precedes.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from weebot.domain.models.event import MessageEvent


class _Bus:
    def __init__(self):
        self.handlers = []

    def subscribe(self, h):
        self.handlers.append(h)

    def unsubscribe(self, h):
        self.handlers.remove(h)


async def _notices(monkeypatch, bursts: int) -> list[dict]:
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.web.routers import sse

    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "false")
    monkeypatch.setattr(sse, "_SUBSCRIBER_QUEUE_MAXSIZE", 1)
    bus = _Bus()
    repo = MagicMock()
    repo.load_session = AsyncMock(return_value=None)
    request = MagicMock()
    ports = {EventBusPort: bus, StateRepositoryPort: repo}
    request.app.state.container.get = lambda key: ports[key]
    gen = (await sse.stream_events(request)).body_iterator
    pending = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0)
    notices = []
    for burst in range(bursts):
        for i in range(3):  # a queue of 1: two of every three are dropped
            await bus.handlers[0](MessageEvent(session_id="s1", message=f"m{burst}{i}"))
        for _ in range(2):  # the notice, then the surviving event
            item = await asyncio.wait_for(pending, 2)
            if item["event"] == "notification":
                notices.append(json.loads(item["data"]))
            pending = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0)
    pending.cancel()
    return notices


async def test_each_drop_notice_has_its_own_id_and_session(monkeypatch):
    notices = await _notices(monkeypatch, bursts=2)
    assert len(notices) == 2
    assert all(n.get("id") and n.get("timestamp") for n in notices)
    assert notices[0]["id"] != notices[1]["id"]
    assert {n["session_id"] for n in notices} == {"s1"}
