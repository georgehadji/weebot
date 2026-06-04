"""SSE route — streams AgentEvents to web UI in real-time.

Maps to Hermes Evolution Phase 2.1.  Uses FastAPI EventSourceResponse
to push AgentEvent serializations as server-sent events.  The frontend
consumes these to display live reasoning, tool execution, and status.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from weebot.application.ports.event_bus_port import EventBusPort, EventHandler
from weebot.domain.models.event import AgentEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stream")
async def stream_events(request: Request):
    """SSE endpoint — streams all AgentEvents as they happen.

    The client connects via EventSource('/api/events/stream').
    Each event is sent as an SSE message with event type and JSON data.

    Example client:
        const evtSource = new EventSource('/api/events/stream');
        evtSource.addEventListener('tool', (e) => {
            const data = JSON.parse(e.data);
            console.log(data.tool_name, data.status);
        });
    """
    event_bus: Optional[EventBusPort] = None
    try:
        container = request.app.state.container
        event_bus = container.get(EventBusPort)
    except (AttributeError, KeyError):
        return JSONResponse(
            status_code=503,
            content={"error": "Event bus not available"},
        )

    async def event_generator():
        """Yield SSE messages for each AgentEvent published on the bus."""
        queue: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue(maxsize=500)

        async def handler(event: AgentEvent) -> None:
            """Push event to the SSE queue (non-blocking, drop on full)."""
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop events if client is too slow

        # Subscribe to ALL agent events
        event_bus.subscribe(handler)

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break  # Sentinel — shutdown

                event_type = getattr(event, "type", "unknown")
                try:
                    data = event.model_dump(mode="json", by_alias=True)
                except Exception:
                    data = {"type": event_type, "error": "serialization_failed"}

                yield {
                    "event": event_type,
                    "data": json.dumps(data, default=str),
                }
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(handler)
            logger.debug("SSE connection closed")

    return EventSourceResponse(event_generator())
