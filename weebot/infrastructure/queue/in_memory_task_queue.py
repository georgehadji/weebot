"""InMemoryTaskQueue — asyncio.PriorityQueue backed implementation.

Default queue backend for ``TaskRunner``.  Non-durable — items are
lost on process restart.
"""

from __future__ import annotations

import asyncio
import logging

from weebot.domain.models.session import Session
from weebot.application.ports.task_queue_port import TaskQueuePort, QueuedSession, FlowFactory

logger = logging.getLogger(__name__)


class InMemoryTaskQueue(TaskQueuePort):
    """In-memory priority queue backed by ``asyncio.PriorityQueue``.

    This is the default backend — no external dependencies, no persistence.
    Items are lost on process restart.
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.PriorityQueue[QueuedSession] = asyncio.PriorityQueue(maxsize=maxsize)
        self._closed = False

    async def enqueue(self, session: Session, flow_factory: FlowFactory, priority: int = 5) -> None:
        if self._closed:
            raise RuntimeError("TaskQueue is closed")
        await self._queue.put(
            QueuedSession(priority=priority, session=session, flow_factory=flow_factory)
        )

    async def dequeue(self) -> QueuedSession | None:
        while not self._closed:
            try:
                # Use wait_for with a short timeout so we periodically
                # check the closed flag.
                return await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
        # Drain remaining items
        try:
            item = self._queue.get_nowait()
            self._queue.task_done()
            return item
        except asyncio.QueueEmpty:
            return None

    async def ack(self, item: QueuedSession) -> None:
        # In-memory queue removes items on dequeue — nothing to do.
        pass

    async def length(self) -> int:
        return self._queue.qsize()

    async def close(self) -> None:
        self._closed = True
        # dequeue() will drain remaining items then return None because
        # the loop checks self._closed after each timeout cycle.


__all__ = ["InMemoryTaskQueue"]
