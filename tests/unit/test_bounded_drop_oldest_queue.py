"""Tests for BoundedDropOldestQueue (Phase 0, T0.5).

Verifies:
  1. Flooding well past capacity never grows the queue past maxsize.
  2. Overflow drops the OLDEST item, not the newest — the consumer sees
     forward progress instead of stalling on stale events.
  3. The dropped counter accumulates across overflow and resets on read.
  4. Under capacity, nothing is dropped and FIFO order is preserved.
"""
from __future__ import annotations

import pytest

from weebot.interfaces.web.bounded_drop_oldest_queue import BoundedDropOldestQueue


def test_flooding_past_capacity_does_not_grow_queue_unbounded():
    queue: BoundedDropOldestQueue[int] = BoundedDropOldestQueue(maxsize=100)

    for i in range(1000):
        queue.try_put(i)

    assert queue.qsize() == 100
    assert queue.take_dropped_count() == 900


@pytest.mark.asyncio
async def test_overflow_drops_oldest_not_newest():
    queue: BoundedDropOldestQueue[int] = BoundedDropOldestQueue(maxsize=3)

    for i in range(5):  # 0,1,2,3,4 — capacity 3, so 0 and 1 are dropped
        queue.try_put(i)

    remaining = [await queue.get() for _ in range(3)]
    assert remaining == [2, 3, 4]


def test_dropped_count_resets_after_read():
    queue: BoundedDropOldestQueue[int] = BoundedDropOldestQueue(maxsize=2)
    for i in range(10):
        queue.try_put(i)

    assert queue.take_dropped_count() == 8
    assert queue.take_dropped_count() == 0  # already consumed


@pytest.mark.asyncio
async def test_under_capacity_nothing_dropped_fifo_preserved():
    queue: BoundedDropOldestQueue[str] = BoundedDropOldestQueue(maxsize=10)
    queue.try_put("a")
    queue.try_put("b")
    queue.try_put("c")

    assert queue.take_dropped_count() == 0
    assert await queue.get() == "a"
    assert await queue.get() == "b"
    assert await queue.get() == "c"
