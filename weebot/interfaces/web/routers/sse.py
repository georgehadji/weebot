"""SSE route — streams AgentEvents to web UI in real-time.

Maps to Hermes Evolution Phase 2.1.  Uses FastAPI EventSourceResponse
to push AgentEvent serializations as server-sent events.  The frontend
consumes these to display live reasoning, tool execution, and status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from weebot.application.ports.event_bus_port import EventBusPort
from weebot.domain.models.event import AgentEvent
from weebot.interfaces.web.bounded_drop_oldest_queue import BoundedDropOldestQueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["events"])

# Per-subscriber bound. A slow client must not grow this process's memory
# without limit — see mission_center_ui_implementation_plan.md T0.5.
_SUBSCRIBER_QUEUE_MAXSIZE = 500


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
    event_bus: EventBusPort | None = None
    try:
        container = request.app.state.container
        event_bus = container.get(EventBusPort)
    except (AttributeError, KeyError):
        return JSONResponse(status_code=503, content={"error": "Event bus not available"})

    # Only the caller's sessions (F58): this streamed every user's events.
    from fastapi import HTTPException

    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.interfaces.web.auth import verify_session_ownership

    state_repo = container.get(StateRepositoryPort)
    allowed: dict[str, bool] = {}

    async def _visible(event: AgentEvent) -> bool:
        sid = getattr(event, "session_id", "") or ""
        if not sid:
            return True  # process-level notices carry no session
        if sid not in allowed:
            session = await state_repo.load_session(sid)
            try:
                await verify_session_ownership(request, session.user_id if session else None)
                allowed[sid] = True
            except HTTPException:
                allowed[sid] = False
        return allowed[sid]

    async def event_generator():
        """Yield SSE messages for each AgentEvent published on the bus."""
        queue: BoundedDropOldestQueue[AgentEvent | None] = BoundedDropOldestQueue(
            maxsize=_SUBSCRIBER_QUEUE_MAXSIZE
        )

        async def handler(event: AgentEvent) -> None:
            """Push event to the SSE queue; never blocks, never raises."""
            queue.try_put(event)

        # Subscribe to ALL agent events
        event_bus.subscribe(handler)

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break  # Sentinel — shutdown
                if not await _visible(event):
                    continue

                dropped = queue.take_dropped_count()
                if dropped > 0:
                    # Its own id: the UI dedupes by id, and dropped every later notice (W2-4).
                    gap_data = {
                        "id": f"drop-{uuid.uuid4().hex}",
                        "type": "notification",
                        "session_id": getattr(event, "session_id", "") or "",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "text": f"{dropped} event(s) dropped — client fell behind",
                    }
                    yield {"event": "notification", "data": json.dumps(gap_data)}

                event_type = getattr(event, "type", "unknown")
                try:
                    data = event.model_dump(mode="json", by_alias=True)
                except Exception:
                    data = {"type": event_type, "error": "serialization_failed"}

                yield {"event": event_type, "data": json.dumps(data, default=str)}
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(handler)
            logger.debug("SSE connection closed")

    return EventSourceResponse(event_generator())
