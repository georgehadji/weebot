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
from weebot.domain.models.event import AgentEvent, FactDiscovered, NotificationEvent

logger = logging.getLogger(__name__)


class EventBrokerAdapter:
    """Maps EventPublisher protocol calls to AsyncEventBus publications.

    Usage:
        adapter = EventBrokerAdapter(async_event_bus)
        await adapter.publish("fact_discovered", "agent-1", {"key": "k", "value": "v"})
    """

    def __init__(self, event_bus: EventBusPort) -> None:
        self._bus = event_bus
        # handler -> the type-filtering wrapper subscribed for it, for unsubscribe().
        self._wrappers: dict[Any, Any] = {}

    async def publish(
        self, event_type: str, agent_id: str, data: dict[str, Any] | None = None
    ) -> bool:
        """Publish an event through the global AsyncEventBus.

        This method satisfies the EventPublisher protocol signature so it
        can be used wherever an EventPublisher is expected (e.g., injected
        into WorkingMemory).
        """
        agent_event = self._convert(event_type, agent_id, data or {})
        if isinstance(agent_event, NotificationEvent) and not agent_event.session_id:
            # An empty session id is a global broadcast to every WebSocket client;
            # an event that names no session has no business there.
            logger.debug("EventBrokerAdapter: dropped '%s' with no session id", event_type)
            return False
        await self._bus.publish(agent_event)
        return True

    def subscribe(self, event_type: str, handler: Any) -> None:
        """Subscribe to events of a given type via the AsyncEventBus.

        This bridges the old EventBroker.subscribe(event_type=…) API
        onto the new AsyncEventBus.subscribe_by_type().  The *handler*
        receives the deserialised AgentEvent subtypes.

        To unsubscribe, call unsubscribe() with the *same handler
        reference*.
        """
        # Filtered here rather than with AsyncEventBus.subscribe_by_type, which
        # the port does not have: the container's DurableEventBus raised on it.
        async def filtered(event: AgentEvent) -> None:
            if getattr(event, "type", None) == event_type:
                await handler(event)

        self._wrappers[handler] = filtered
        self._bus.subscribe(filtered)

    def unsubscribe(self, handler: Any) -> None:
        """Stop delivering to *handler* (the same reference given to subscribe)."""
        wrapper = self._wrappers.pop(handler, None)
        if wrapper is not None:
            self._bus.unsubscribe(wrapper)

    def _convert(self, event_type: str, agent_id: str, data: dict[str, Any]) -> AgentEvent:
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

        # Fallback: wrap as a NotificationEvent so nothing is silently dropped.
        #
        # `session_id` must be carried through from *data*, as the branch above
        # already does. An empty one is not neutral: the WebSocket broadcaster
        # routes on it, and empty means *global* -- deliberately, so that
        # SessionPresenceEvent can feed a rail watching every session. This
        # text embeds up to 200 characters of the caller's arbitrary payload,
        # so leaving it unset would put one session's data on the channel every
        # authenticated client is listening to.
        logger.debug(
            "EventBrokerAdapter: mapping '%s' from agent '%s' to NotificationEvent",
            event_type,
            agent_id,
        )
        return NotificationEvent(
            session_id=data.get("session_id", ""),
            text=f"[{event_type}] from {agent_id}: {str(data)[:200]}",
        )
