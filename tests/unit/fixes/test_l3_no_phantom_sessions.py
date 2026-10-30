"""L3 (remaining-work plan 2026-10-29): a global event does not become a phantom session.

``DurableEventBus`` journaled an event with an empty ``session_id`` under the event's own
uuid, and ``log_event`` created an event-store session for it. Every session status change
publishes such an event (``SessionPresenceEvent`` is global on purpose), so every run left
phantom sessions behind. An event that names no session is now not journaled; presence is
not journaled under its subject either, as it would count as one of the session's events.
"""

from __future__ import annotations

from weebot.domain.models.event import MessageEvent, SessionPresenceEvent
from weebot.infrastructure.event_bus import AsyncEventBus, DurableEventBus
from weebot.infrastructure.event_store import AsyncEventStore


async def test_presence_creates_no_session(tmp_path):
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    bus = DurableEventBus(AsyncEventBus(), store)
    await bus.publish(SessionPresenceEvent(about_session_id="real", status="running"))
    assert await store.list_sessions() == []


async def test_a_session_event_is_still_journaled(tmp_path):
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    bus = DurableEventBus(AsyncEventBus(), store)
    await bus.publish(MessageEvent(session_id="real", role="user", message="hi"))
    assert [s.id for s in await store.list_sessions()] == ["real"]
