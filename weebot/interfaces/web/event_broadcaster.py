"""Event broadcaster that bridges EventBusPort to WebSocket connections."""
from __future__ import annotations

import json
import logging
from typing import Any

from weebot.application.ports.event_publisher_port import EventPublisherPort
from weebot.domain.models.event import AgentEvent
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
            session_id = getattr(event, 'session_id', None)
            
            if session_id:
                await self._manager.broadcast_to_session(session_id, event_dict)
            else:
                # Broadcast to global connections if no session_id
                await self._manager.broadcast_global(event_dict)
                
        except Exception as e:
            logger.error(f"Failed to broadcast event: {e}")

    def _event_to_dict(self, event: AgentEvent) -> dict[str, Any]:
        """Convert AgentEvent to dictionary for JSON serialization."""
        # Handle Pydantic models
        if hasattr(event, 'model_dump'):
            return event.model_dump()
        # Handle dataclasses or regular objects
        return {
            'type': getattr(event, 'type', 'unknown'),
            **{
                k: v for k, v in event.__dict__.items() 
                if not k.startswith('_')
            }
        }
