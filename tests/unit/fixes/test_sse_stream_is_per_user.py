"""/api/events/stream sends only events from the caller's sessions (F58).

It subscribed to the whole bus and forwarded every event, so any caller saw
every user's tool calls and messages live.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session


class _Bus:
    def __init__(self):
        self.handlers = []

    def subscribe(self, h):
        self.handlers.append(h)

    def unsubscribe(self, h):
        self.handlers.remove(h)


async def test_other_users_events_are_not_streamed(monkeypatch):
    from weebot.application.ports.event_bus_port import EventBusPort
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.web.routers import sse

    monkeypatch.setenv("WEEBOT_ENFORCE_SESSION_OWNERSHIP", "true")
    bus = _Bus()
    owners = {"a1": Session(id="a1", user_id="alice"), "b1": Session(id="b1", user_id="bob")}
    repo = MagicMock()
    repo.load_session = AsyncMock(side_effect=lambda sid: owners.get(sid))
    request = MagicMock()
    request.app.state.container.get = lambda key: {EventBusPort: bus, StateRepositoryPort: repo}[key]

    with patch("weebot.interfaces.web.auth._resolve_user", AsyncMock(return_value="alice")):
        resp = await sse.stream_events(request)
        gen = resp.body_iterator
        first = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0)
        for h in list(bus.handlers):
            await h(MessageEvent(session_id="b1", message="bob's secret"))
            await h(MessageEvent(session_id="a1", message="alice's"))
        item = await asyncio.wait_for(first, 2)
    text = item["data"] if isinstance(item, dict) else str(item)
    assert "alice's" in text and "bob" not in text
