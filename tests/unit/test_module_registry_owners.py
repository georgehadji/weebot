"""Plan Phase 8: each process-level registry has a documented owner and a working reset.

A module-level dict or handle is global state; it is acceptable only if something owns
its lifetime and a test (or shutdown) can put it back to empty. These four are the ones
the ARCHITECTURE.md state inventory lists.
"""

from __future__ import annotations

import pytest

from weebot.core import behavior_tracker
from weebot.infrastructure.persistence import connection_pool
from weebot.interfaces import factories
from weebot.tools import advanced_browser


class _Stoppable:
    def __init__(self) -> None:
        self.stopped = 0

    def stop(self) -> None:
        self.stopped += 1


def test_stop_all_trackers_stops_and_empties_the_registry(monkeypatch):
    first, second = _Stoppable(), _Stoppable()
    monkeypatch.setattr(behavior_tracker, "_tracker_registry", {"a": first, "b": second})
    behavior_tracker.stop_all_trackers()
    assert (first.stopped, second.stopped) == (1, 1)
    assert behavior_tracker._tracker_registry == {}


@pytest.mark.asyncio
async def test_close_all_pools_closes_and_empties_the_registry(monkeypatch):
    class Pool:
        closed = 0

        async def close(self):
            Pool.closed += 1

    monkeypatch.setattr(connection_pool, "_pool_registry", {"x.db": Pool(), "y.db": Pool()})
    await connection_pool.close_all_pools()
    assert Pool.closed == 2
    assert connection_pool._pool_registry == {}


def test_reset_shared_container_lets_the_next_call_build_a_new_one(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(factories, "_shared_container", sentinel)
    assert factories.shared_container() is sentinel
    factories.reset_shared_container()
    assert factories._shared_container is None


def test_the_playwright_atexit_backstop_stops_and_zeroes_the_handle(monkeypatch):
    pw = _Stoppable()
    monkeypatch.setattr(advanced_browser, "_playwright_instance", pw)
    advanced_browser._atexit_cleanup_playwright()
    assert pw.stopped == 1
    assert advanced_browser._playwright_instance is None
