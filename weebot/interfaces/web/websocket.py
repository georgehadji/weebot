"""WebSocket connection manager for real-time event streaming."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Set

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections per session."""

    def __init__(self) -> None:
        # session_id -> set of WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        # Global connections (for broadcasts)
        self._global_connections: Set[WebSocket] = set()
        # Locks for thread-safe access
        self._connections_lock = asyncio.Lock()
        self._global_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str | None = None) -> None:
        """Accept a new WebSocket connection."""
        try:
            await websocket.accept()
        except Exception as e:
            logger.error(f"Failed to accept WebSocket connection: {e}")
            raise
        
        if session_id:
            async with self._connections_lock:
                if session_id not in self._connections:
                    self._connections[session_id] = set()
                self._connections[session_id].add(websocket)
            logger.debug(f"WebSocket connected for session {session_id}")
        else:
            async with self._global_lock:
                self._global_connections.add(websocket)
            logger.debug("Global WebSocket connected")

    async def disconnect(self, websocket: WebSocket, session_id: str | None = None) -> None:
        """Remove a WebSocket connection."""
        if session_id:
            async with self._connections_lock:
                if session_id in self._connections:
                    self._connections[session_id].discard(websocket)
                    if not self._connections[session_id]:
                        del self._connections[session_id]
            logger.debug(f"WebSocket disconnected from session {session_id}")
        
        async with self._global_lock:
            self._global_connections.discard(websocket)

    async def broadcast_to_session(
        self, 
        session_id: str, 
        message: dict | str
    ) -> None:
        """Broadcast a message to all connections for a session."""
        async with self._connections_lock:
            if session_id not in self._connections:
                return
            # Iterate over a copy to avoid "Set changed size during iteration"
            connections = list(self._connections[session_id])

        payload = json.dumps(message) if isinstance(message, dict) else message
        disconnected = set()

        for connection in connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        if disconnected:
            async with self._connections_lock:
                for conn in disconnected:
                    self._connections[session_id].discard(conn)

    async def broadcast_global(self, message: dict | str) -> None:
        """Broadcast to all global connections."""
        async with self._global_lock:
            # Iterate over a copy to avoid "Set changed size during iteration"
            connections = list(self._global_connections)

        payload = json.dumps(message) if isinstance(message, dict) else message
        disconnected = set()

        for connection in connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Failed to send to global WebSocket: {e}")
                disconnected.add(connection)

        if disconnected:
            async with self._global_lock:
                for conn in disconnected:
                    self._global_connections.discard(conn)


# Global connection manager instance
manager = ConnectionManager()
