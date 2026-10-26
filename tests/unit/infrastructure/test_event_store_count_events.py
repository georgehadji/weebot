"""EventStorePort.count_events: one grouped read per list page (UI/UX plan, Phase 2).

`SessionResponse.event_count` was `len(session.events)` on a row that never holds events, so
every session read "0 events". The counts belong to the event store.
"""

from __future__ import annotations

import pytest

from tests.unit.test_effect_ledger import MemoryEventStore
from weebot.infrastructure.event_store import AsyncEventStore


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "sqlite":
        return AsyncEventStore(db_path=str(tmp_path / "events.db"))
    return MemoryEventStore()


async def _seed(store) -> None:
    for _ in range(3):
        await store.log_event("a", "message", {})
    await store.log_event("b", "step", {})


async def test_counts_events_per_session(store):
    await _seed(store)
    assert await store.count_events(["a", "b"]) == {"a": 3, "b": 1}


async def test_every_requested_id_is_a_key_even_with_no_events(store):
    await _seed(store)
    assert await store.count_events(["a", "ghost"]) == {"a": 3, "ghost": 0}


async def test_unrequested_sessions_are_left_out(store):
    await _seed(store)
    assert await store.count_events(["b"]) == {"b": 1}


async def test_no_ids_is_an_empty_answer(store):
    assert await store.count_events([]) == {}


async def test_more_ids_than_one_sql_chunk(tmp_path):
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    await store.log_event("s-7", "message", {})
    await store.log_event("s-1234", "message", {})
    ids = [f"s-{i}" for i in range(1500)]
    counts = await store.count_events(ids)
    assert len(counts) == 1500
    assert (counts["s-7"], counts["s-1234"], counts["s-0"]) == (1, 1, 0)
