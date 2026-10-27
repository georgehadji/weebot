"""Problems the map re-read found in source (2026-10-27), each confirmed before the fix.

- The circuit breaker trips at 5 consecutive failures but logged "tripped" at 3.
- The "all models tripped" error told the operator to check OpenRouter credits even
  when the cause was a bad API key or an unknown model name.
- `EventPublisher` was handed an `emit_lock` and never took it, so two concurrent
  emits could finish their session writes out of order and leave the older snapshot
  in the database.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.domain.models.event import MessageEvent
from weebot.domain.models.session import Session


def _breaker():
    ex = CascadeExecutor.__new__(CascadeExecutor)
    ex._circuit_breaker_failures = {}
    return ex


def test_the_trip_threshold_is_read_from_the_instance():
    ex = _breaker()
    ex._BREAKER_TRIP_AT = 2
    ex._cascade_record_failure("m")
    assert not ex.cascade_is_tripped("m")
    ex._cascade_record_failure("m")
    assert ex.cascade_is_tripped("m")


def test_the_breaker_says_tripped_only_when_it_trips(caplog):
    ex = _breaker()
    with caplog.at_level(logging.INFO):
        for _ in range(4):
            ex._cascade_record_failure("m")
        assert not ex.cascade_is_tripped("m")
        assert not any("tripped" in r.getMessage().lower() for r in caplog.records)
        ex._cascade_record_failure("m")
    assert ex.cascade_is_tripped("m")
    assert any("tripped" in r.getMessage().lower() for r in caplog.records)


class _SlowFirstSave:
    """A state repo whose first write is slow, like a retried write."""

    def __init__(self):
        self.calls = 0
        self.finished: list[int] = []

    async def save_session(self, session):
        self.calls += 1
        snapshot = len(session.events)
        if self.calls == 1:
            await asyncio.sleep(0.05)
        self.finished.append(snapshot)


@pytest.mark.asyncio
async def test_concurrent_emits_persist_in_order():
    from weebot.application.flows.event_publisher import EventPublisher

    repo = _SlowFirstSave()
    publisher = EventPublisher(Session(id="s", task="t"), state_repo=repo)
    await asyncio.gather(
        publisher.emit(MessageEvent(message="a")), publisher.emit(MessageEvent(message="b"))
    )
    assert repo.finished == sorted(repo.finished), (
        f"an older snapshot was written last: {repo.finished}"
    )
    assert repo.finished[-1] == 2


@pytest.mark.asyncio
async def test_waiting_emits_do_not_each_repeat_a_slow_save():
    """Five emits queue behind one slow write; the next save covers the other four."""
    from weebot.application.flows.event_publisher import EventPublisher

    repo = _SlowFirstSave()
    publisher = EventPublisher(Session(id="s", task="t"), state_repo=repo)
    await asyncio.gather(*(publisher.emit(MessageEvent(message=str(i))) for i in range(5)))
    assert repo.calls == 2, f"{repo.calls} saves for 5 emits"
    assert repo.finished[-1] == 5, "the last save must hold every event"
