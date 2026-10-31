"""Event broadcaster that bridges EventBusPort to WebSocket connections."""

from __future__ import annotations

import logging
from typing import Any

from weebot.application.ports.event_publisher_port import EventPublisherPort
from weebot.domain.models.event import AgentEvent, SessionPresenceEvent
from .websocket import ConnectionManager

logger = logging.getLogger(__name__)


class WebSocketEventBroadcaster(EventPublisherPort):
    """Broadcasts events to WebSocket clients.

    This adapter implements ``EventPublisherPort`` — the minimal publishing
    interface — to receive events from the internal event system and forward
    them to connected WebSocket clients.
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        self._manager = connection_manager

    async def publish(self, event: AgentEvent) -> None:
        """Publish event to WebSocket clients.

        Extracts session_id from the event and broadcasts to session-specific
        WebSocket connections.
        """
        try:
            # Convert event to dict
            event_dict = self._event_to_dict(event)

            # Extract session_id from event if available
            session_id = getattr(event, "session_id", None)

            if session_id:
                await self._manager.broadcast_to_session(session_id, event_dict)
            else:
                # Broadcast to global connections if no session_id; a presence frame goes
                # only to its session's owner, unless ownership is not enforced.
                await self._manager.broadcast_global(
                    event_dict, only_principal=self._presence_owner(event)
                )

        except Exception as e:
            logger.error(f"Failed to broadcast event: {e}")

    @staticmethod
    def _presence_owner(event: AgentEvent) -> str | None:
        from weebot.interfaces.web.auth import ownership_enforced

        if isinstance(event, SessionPresenceEvent) and event.owner_user_id and ownership_enforced():
            return event.owner_user_id
        return None

    def _event_to_dict(self, event: AgentEvent) -> dict[str, Any]:
        """Convert AgentEvent to a JSON-safe dictionary.

        ``mode="json"`` is required — the default ``model_dump()`` leaves
        ``datetime``/``Enum`` fields as native Python objects, which
        ``ConnectionManager.broadcast_to_session``'s plain ``json.dumps``
        cannot serialize (raises ``TypeError`` and silently drops the event).
        """
        if hasattr(event, "model_dump"):
            return event.model_dump(mode="json")
        # Handle dataclasses or regular objects
        return {
            "type": getattr(event, "type", "unknown"),
            **{k: v for k, v in event.__dict__.items() if not k.startswith("_")},
        }
