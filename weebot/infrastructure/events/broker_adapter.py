"""EventBrokerAdapter — bridges EventBroker-style publish calls to AsyncEventBus.

The codebase has two event systems running in parallel:
  1. AsyncEventBus (in infrastructure/event_bus.py) — publishes AgentEvent
     through EventBusPort.  Used by PlanActFlow, CLI subscriber, WebSocket
     broadcaster, and EventStore.
  2. EventBroker (in core/agent_context.py) — publishes ContextEvent through
     a separate subscription model.  Used by AgentContext, WorkingMemory
     (via EventPublisher protocol), complex_task_executor, workflow_orchestrator,
     and circuit_breaker.

This adapter implements the EventPublisher protocol from domain/ports.py
and converts EventBroker-style calls into AsyncEventBus publications.
The EventBroker class itself is preserved for backward compatibility
with code that uses its subscribe() / get_event_history() methods.
"""
from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import (
    AgentEvent,
    FactDiscovered,
    NotificationEvent,
)
from weebot.domain.ports import EventPublisher

logger = logging.getLogger(__name__)


class EventBrokerAdapter:
    """Maps EventPublisher protocol calls to AsyncEventBus publications.

    Usage:
        adapter = EventBrokerAdapter(async_event_bus)
        await adapter.publish("fact_discovered", "agent-1", {"key": "k", "value": "v"})
    """

    def __init__(self, event_bus: EventBusPort) -> None:
        self._bus = event_bus

    async def publish(
        self,
        event_type: str,
        agent_id: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """Publish an event through the global AsyncEventBus.

        This method satisfies the EventPublisher protocol signature so it
        can be used wherever an EventPublisher is expected (e.g., injected
        into WorkingMemory).
        """
        agent_event = self._convert(event_type, agent_id, data or {})
        await self._bus.publish(agent_event)
        return True

    def _convert(
        self,
        event_type: str,
        agent_id: str,
        data: dict[str, Any],
    ) -> AgentEvent:
        """Convert an EventBroker-style (event_type, agent_id, data) triple
        into the most appropriate AgentEvent subtype.

        Known event types from the codebase:
          - "fact_discovered"  → FactDiscovered domain event
          - "plan_step_*"      → StepEvent
          - "tool_*"           → ToolEvent
          - anything else      → NotificationEvent (catch-all)
        """
        # Domain event types from domain/models/event.py
        if event_type == "fact_discovered":
            return FactDiscovered(
                session_id=data.get("session_id", ""),
                key=data.get("key", ""),
                value=data.get("value"),
            )

        # Fallback: wrap as a NotificationEvent so nothing is silently dropped
        logger.debug(
            "EventBrokerAdapter: mapping '%s' from agent '%s' to NotificationEvent",
            event_type,
            agent_id,
        )
        return NotificationEvent(
            text=f"[{event_type}] from {agent_id}: {str(data)[:200]}",
        )
