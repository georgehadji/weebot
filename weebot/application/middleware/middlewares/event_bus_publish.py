"""Event bus publish middleware — publishes events to the message bus."""
from __future__ import annotations

from typing import Any

from weebot.application.middleware.event_middleware import EventMiddleware
from weebot.domain.models.event import AgentEvent


class EventBusPublishMiddleware(EventMiddleware):
    """Publishes the event to the event bus and emits domain events.

    Does nothing if no event_bus is configured on the flow.
    """

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        flow = context.get("flow")
        event_bus = context.get("event_bus")

        if event_bus is not None:
            await event_bus.publish(event)
            # Publish domain events for key agent event types
            if flow is not None and hasattr(flow, "_emit_domain_event"):
                await flow._emit_domain_event(event)

        return event
