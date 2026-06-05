"""[DEPRECATED] No adapter implementation exists.
Tracked in docs/plans/ARCHITECTURE_9_PLAN.md.
"""
"""Swarm Event Bus port — abstract interface for inter-agent message routing.

Created as part of architecture remediation (step-7f) to remove the
direct infrastructure dependency from weebot/tools/swarm.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SwarmEventBusPort(ABC):
    """Abstract interface for publishing and subscribing to swarm events."""

    @abstractmethod
    async def publish(self, topic: str, message: Any) -> None:
        """Publish a message to a topic."""
        ...

    @abstractmethod
    async def subscribe(self, topic: str, handler) -> None:
        """Register a handler for a topic."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
