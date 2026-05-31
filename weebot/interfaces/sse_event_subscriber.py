"""SSE stream subscriber — yields Server-Sent Events formatted strings from the event bus."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    MessageEvent,
    PlanEvent,
    StepEvent,
    TitleEvent,
    ToolEvent,
    WaitForUserEvent,
)


class SSEEventSubscriber:
    """Event subscriber that formats agent events as SSE data lines."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._handler_id: Optional[int] = None

    async def _on_event(self, event: AgentEvent) -> None:
        await self._queue.put(event)

    def subscribe_to(self, bus: EventBusPort) -> None:
        """Register this subscriber on the given event bus."""
        # EventBusPort interface uses simple subscribe; we store the coroutine function reference
        bus.subscribe(self._on_event)

    def unsubscribe_from(self, bus: EventBusPort) -> None:
        """Unregister this subscriber from the given event bus."""
        bus.unsubscribe(self._on_event)

    async def stream(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted data lines forever (or until consumer disconnects)."""
        while True:
            event = await self._queue.get()
            payload = self._serialize(event)
            yield f"data: {payload}\n\n"

    def _serialize(self, event: AgentEvent) -> str:
        """Convert an agent event to a JSON string suitable for SSE."""
        base = {
            "type": event.type,
            "id": event.id,
            "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
        }
        if isinstance(event, MessageEvent):
            base["role"] = event.role
            base["message"] = event.message
        elif isinstance(event, PlanEvent):
            base["status"] = event.status.value if hasattr(event.status, "value") else str(event.status)
            base["plan"] = event.plan
            base["step"] = event.step
        elif isinstance(event, StepEvent):
            base["step_id"] = event.step_id
            base["description"] = event.description
            base["status"] = event.status.value if hasattr(event.status, "value") else str(event.status)
        elif isinstance(event, ToolEvent):
            base["tool_name"] = event.tool_name
            base["function_name"] = event.function_name
            base["status"] = event.status.value if hasattr(event.status, "value") else str(event.status)
            base["result"] = event.result
        elif isinstance(event, TitleEvent):
            base["title"] = event.title
        elif isinstance(event, ErrorEvent):
            base["error"] = event.error
        elif isinstance(event, WaitForUserEvent):
            base["question"] = event.question
        elif isinstance(event, DoneEvent):
            base["done"] = True
        return json.dumps(base)
