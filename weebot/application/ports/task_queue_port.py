"""TaskQueuePort — abstract interface for a durable session queue.

Allows ``TaskRunner`` to work with either the default in-memory queue
or a Redis-backed queue (behind the ``WEEBOT_QUEUE_BACKEND=redis``
feature flag).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from weebot.application.abstractions import BaseFlow
from weebot.domain.models.session import Session

FlowFactory = Callable[[Session], BaseFlow]


@dataclass(order=True)
class QueuedSession:
    """A session + factory waiting in the queue.

    ``priority`` is the sort key (lower = sooner).  ``session`` and
    ``flow_factory`` are the payload carried by the queue item.
    """
    priority: int
    session: Session = field(compare=False)
    flow_factory: FlowFactory = field(compare=False)


class TaskQueuePort(ABC):
    """Durable queue interface for session execution scheduling.

    Default implementation is ``InMemoryTaskQueue`` (asyncio.PriorityQueue).
    Redis-backed implementation uses Redis Streams with consumer groups.
    """

    @abstractmethod
    async def enqueue(
        self,
        session: Session,
        flow_factory: FlowFactory,
        priority: int = 5,
    ) -> None:
        """Add a session to the queue.

        Args:
            session: The session to execute.
            flow_factory: Factory that creates a flow for the session.
            priority: Lower values are dequeued first (default 5).
        """
        ...

    @abstractmethod
    async def dequeue(self) -> QueuedSession | None:
        """Remove and return the next session from the queue.

        Blocks until an item is available or ``close()`` is called.
        Returns ``None`` when the queue is closed and drained.
        """
        ...

    @abstractmethod
    async def ack(self, item: QueuedSession) -> None:
        """Acknowledge a dequeued session as processed (idempotent).

        For Redis Streams this translates to ``XACK``.  For the
        in-memory queue this is a no-op since items are removed
        on dequeue.
        """
        ...

    @abstractmethod
    async def length(self) -> int:
        """Return the number of pending items in the queue."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Shut down the queue, releasing any resources.

        In-flight items are lost unless the backend persists them
        (Redis).  The in-memory queue simply drains and cancels
        any blocking ``dequeue()`` call.
        """
        ...


__all__ = ["TaskQueuePort", "QueuedSession", "FlowFactory"]
