"""Base flow for agent execution."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator

from weebot.domain.models.event import AgentEvent


class BaseFlow(ABC):
    """Abstract base for all agent flows."""

    @abstractmethod
    async def run(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
        """Execute the flow for the given prompt, yielding events."""
        ...

    @abstractmethod
    def is_done(self) -> bool:
        """Return True if the flow has completed."""
        ...
