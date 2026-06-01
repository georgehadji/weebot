"""InMemoryTaskQueue — asyncio.PriorityQueue-based TaskQueuePort adapter."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from weebot.application.ports.task_queue_port import TaskQueuePort, FlowFactory
from weebot.domain.models.session import Session


@dataclass(order=True)
class _PrioritizedItem:
    priority: int
    session: Session = field(compare=False)
    factory: FlowFactory = field(compare=False)


class InMemoryTaskQueue(TaskQueuePort):
    """In-memory priority queue for session dispatch.

    Default adapter for development and single-process deployment.
    Replace with RedisTaskQueue for multi-process / durable delivery.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.PriorityQueue[_PrioritizedItem] = (
            asyncio.PriorityQueue(maxsize=maxsize)
        )

    async def enqueue(
        self,
        session: Session,
        flow_factory: FlowFactory,
        priority: int = 5,
    ) -> None:
        await self._queue.put(_PrioritizedItem(priority, session, flow_factory))

    async def dequeue(self) -> Optional[tuple[Session, FlowFactory]]:
        try:
            item = await self._queue.get()
            self._queue.task_done()
            return item.session, item.factory
        except asyncio.CancelledError:
            return None

    async def ack(self, session_id: str) -> None:
        pass  # In-memory queue has no durability concern

    async def size(self) -> int:
        return self._queue.qsize()
