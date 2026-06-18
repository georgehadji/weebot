"""Event middleware abstraction — composable processing for flow events.

Each middleware implements ``process(event, context)`` and can:
- Inspect/modify the event before it reaches session storage
- Read/write to the shared ``context`` dict (which carries the session,
  flow reference, facts, and other mutable state)
- Short-circuit by returning a modified event or raising

The context dict includes:
  - session: the current Session object
  - flow: the PlanActFlow instance (for state access)
  - event_bus: the EventBusPort (if configured)
  - state_repo: the StateRepositoryPort (if configured)
  - emit_lock: asyncio.Lock for serializing DB writes
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.event import AgentEvent


class EventMiddleware(ABC):
    """Processes an event before it reaches session/event-bus/persistence.

    Middlewares are chained in order.  Each receives the event returned
    by the previous middleware.  The context dict is shared across all
    middlewares in the chain.
    """

    @abstractmethod
    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        """Process *event* in the given *context*.

        Args:
            event: The incoming agent event (may be mutated).
            context: Shared mutable dict with keys
                ``session``, ``flow``, ``event_bus``, ``state_repo``, ``emit_lock``.

        Returns:
            The (possibly modified) event for the next middleware.
        """
        ...


class EventPipeline:
    """A chain of middlewares applied to every event emitted by a flow.

    Usage:
        pipeline = EventPipeline([
            TruthBindingMiddleware(),
            CredentialSanitizerMiddleware(),
            SessionMutationMiddleware(),
            EventBusPublishMiddleware(),
            PersistenceMiddleware(),
        ])
        event = await pipeline.process(event, context)
    """

    def __init__(self, middlewares: list[EventMiddleware]) -> None:
        self._middlewares = list(middlewares)

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        """Run *event* through all middlewares in registration order."""
        for mw in self._middlewares:
            event = await mw.process(event, context)
        return event

    def append(self, middleware: EventMiddleware) -> None:
        """Add a middleware to the end of the chain."""
        self._middlewares.append(middleware)
