"""BoundedDropOldestQueue — asyncio.Queue wrapper with visible backpressure.

Used by slow SSE/WebSocket subscribers: instead of blocking the publisher
or silently discarding new events when a client falls behind, the stalest
queued item is discarded to admit the fresh one, and the discard is
counted so the caller can surface a gap marker to the client.

Lives in interfaces/web/ (not infrastructure/) because its only consumer
is the SSE router in this same package — it is transport-layer machinery,
not a port adapter, and interfaces must not import infrastructure
directly (see .importlinter's "Interfaces must not depend on
infrastructure adapters directly" contract).
"""

from __future__ import annotations

import asyncio
from typing import Generic, TypeVar

T = TypeVar("T")


class BoundedDropOldestQueue(Generic[T]):
    """A bounded queue that drops its oldest item on overflow, visibly."""

    def __init__(self, maxsize: int) -> None:
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self._dropped_count = 0

    def try_put(self, item: T) -> None:
        """Enqueue *item*, dropping the oldest queued item if full.

        Never blocks and never raises — a queue that is momentarily full
        on both the drop and the retry (a concurrent consumer racing us)
        simply skips this item; it will be picked up on the next publish.
        """
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._dropped_count += 1
                self._queue.put_nowait(item)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def get(self) -> T:
        return await self._queue.get()

    def take_dropped_count(self) -> int:
        """Return and reset the number of items dropped since the last call."""
        count = self._dropped_count
        self._dropped_count = 0
        return count

    def qsize(self) -> int:
        return self._queue.qsize()
