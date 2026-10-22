"""DurableEventBus journals events the store can encode (found in plan B2c).

`_journal_agent` passed `event.model_dump()` to `EventStore.log_event`, which
calls `json.dumps(data)`. Every event has a datetime `timestamp`, so every
write raised "Object of type datetime is not JSON serializable" and the web
run journaled nothing; the failure was only a warning.
"""

from __future__ import annotations

import json

from weebot.domain.models.event import MessageEvent, PlanStepCompleted
from weebot.infrastructure.event_bus import AsyncEventBus, DurableEventBus


class _JsonStore:
    """Encodes like the SQLite EventStore does."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    async def log_event(self, session_id, event_type, data, cost=0.0, model="", tokens_used=0):
        self.rows.append((event_type, json.dumps(data)))
        return len(self.rows)


async def test_an_agent_event_with_a_timestamp_is_journaled():
    store = _JsonStore()
    bus = DurableEventBus(AsyncEventBus(), store)
    await bus.publish(MessageEvent(role="user", message="hi"))
    assert [r[0] for r in store.rows] == ["message"]


async def test_a_domain_event_is_journaled():
    store = _JsonStore()
    bus = DurableEventBus(AsyncEventBus(), store)
    await bus.publish_domain_event(PlanStepCompleted(session_id="s1", step_id="st1"))
    assert len(store.rows) == 1
