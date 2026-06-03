"""TaskRouterPort — classifies and routes user queries to the appropriate flow.

Enhancement 6 — Neural Task Router.  Implementations:
- KeywordTaskRouter (always available, rule-based)
- BARTTaskRouter (optional, ML-based, requires pip install weebot[router])
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.task_route import TaskRoute


class TaskRouterPort(ABC):
    """Classify a user query and produce a routing decision."""

    @abstractmethod
    async def route(self, query: str) -> TaskRoute:
        """Classify *query* and return a TaskRoute.

        Must not raise exceptions.  Returns TaskRoute(category=UNKNOWN)
        as a safe fallback.
        """
        ...

    @abstractmethod
    async def refresh(self) -> None:
        """Reload classification config (for hot-reload)."""
        ...
