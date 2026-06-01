"""TaskQueuePort — abstract task queue for durable session dispatch.

Allows TaskRunner to decouple session submission from execution,
supporting both in-memory (default) and durable (Redis / RabbitMQ)
backends.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from weebot.domain.models.session import Session

FlowFactory = Callable[[Session], Any]


class TaskQueuePort(ABC):
    """Abstract queue for prioritized session execution."""

    @abstractmethod
    async def enqueue(
        self,
        session: Session,
        flow_factory: FlowFactory,
        priority: int = 5,
    ) -> None:
        """Submit a session for deferred execution."""
        ...

    @abstractmethod
    async def dequeue(self) -> Optional[tuple[Session, FlowFactory]]:
        """Return the next session+factory pair, or None if empty."""
        ...

    @abstractmethod
    async def ack(self, session_id: str) -> None:
        """Mark a session as consumed (for durable queues)."""
        ...

    @abstractmethod
    async def size(self) -> int:
        """Return the number of pending sessions."""
        ...
