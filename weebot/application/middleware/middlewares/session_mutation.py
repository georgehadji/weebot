"""Session mutation middleware — applies event to in-memory session."""
from __future__ import annotations

from typing import Any

from weebot.application.middleware.event_middleware import EventMiddleware
from weebot.domain.models.event import AgentEvent


class SessionMutationMiddleware(EventMiddleware):
    """Mutates the in-memory session by adding the event.

    Updates the context's ``session`` key so subsequent middlewares
    see the updated session.  Also triggers checkpoints for step events.
    """

    async def process(self, event: AgentEvent, context: dict[str, Any]) -> AgentEvent:
        session = context.get("session")
        if session is None:
            return event

        # Apply the event to create a new session copy
        new_session = session.add_event(event)
        context["session"] = new_session

        # Save checkpoint after step completions (best-effort, non-blocking)
        flow = context.get("flow")
        if event.type == "step" and flow is not None and hasattr(flow, "_maybe_save_checkpoint"):
            await flow._maybe_save_checkpoint()

        return event
