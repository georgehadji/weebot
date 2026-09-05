"""WebSocket connection manager for real-time event streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

# How long a single send may take before the peer is treated as gone.
#
# A WebSocket send blocks until the peer's receive window opens, so a client
# that stops reading -- suspended laptop, wedged browser tab, half-open TCP
# connection -- makes its send never return. Without a bound, one such client
# holds a broadcast open for the life of the process.
_WS_SEND_TIMEOUT = 5.0

_C = TypeVar("_C")


async def fan_out(
    connections: Iterable[_C],
    send: Callable[[_C], Awaitable[None]],
    *,
    timeout: float,
    what: str = "WebSocket",
) -> set[_C]:
    """Deliver to every connection concurrently and report the ones that failed.

    Concurrent rather than sequential, because a sequential loop makes every
    client wait for the slowest one ahead of it: a single peer that stops
    reading starves everybody behind it in the list. Bounded rather than
    open-ended, because "stops reading" is indistinguishable from "will read
    eventually" and only a clock can tell them apart.

    A timed-out send is cancelled rather than left pending -- the peer is not
    draining, so the send would otherwise stay alive holding its payload for as
    long as the process runs.

    ``timeout`` is required, not defaulted: each caller states the bound its own
    clients are held to, so there is no shared default to drift out of sync.

    Returns the connections that raised or timed out, for the caller to evict.
    Never raises for a single client's failure; an outer cancellation still
    propagates, since ``CancelledError`` is not an ``Exception``.
    """
    conns = list(connections)
    if not conns:
        return set()

    async def _deliver(conn: _C) -> _C | None:
        try:
            await asyncio.wait_for(send(conn), timeout=timeout)
        except TimeoutError:
            logger.warning("%s send exceeded %ss; dropping unresponsive client", what, timeout)
            return conn
        except Exception as e:
            logger.warning(f"Failed to send to {what}: {e}")
            return conn
        return None

    results = await asyncio.gather(*(_deliver(c) for c in conns))
    return {c for c in results if c is not None}


class ConnectionManager:
    """Manage WebSocket connections per session."""

    def __init__(self) -> None:
        # session_id -> set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}
        # Global connections (for broadcasts)
        self._global_connections: set[WebSocket] = set()
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

    async def broadcast_to_session(self, session_id: str, message: dict | str) -> None:
        """Broadcast a message to all connections for a session."""
        async with self._connections_lock:
            if session_id not in self._connections:
                return
            # Iterate over a copy to avoid "Set changed size during iteration"
            connections = list(self._connections[session_id])

        payload = json.dumps(message) if isinstance(message, dict) else message
        disconnected = await fan_out(
            connections,
            lambda c: c.send_text(payload),
            timeout=_WS_SEND_TIMEOUT,
            what="WebSocket",
        )

        # Clean up disconnected clients.
        # Guard: the session may have been removed by disconnect() between
        # the first lock acquisition (copy) and this second acquisition
        # (cleanup).  If that happened, the key no longer exists and we
        # must not attempt to discard from a missing set.
        if disconnected:
            async with self._connections_lock:
                if session_id in self._connections:
                    for conn in disconnected:
                        self._connections[session_id].discard(conn)

    async def broadcast_global(self, message: dict | str) -> None:
        """Broadcast to all global connections."""
        async with self._global_lock:
            # Iterate over a copy to avoid "Set changed size during iteration"
            connections = list(self._global_connections)

        payload = json.dumps(message) if isinstance(message, dict) else message
        disconnected = await fan_out(
            connections,
            lambda c: c.send_text(payload),
            timeout=_WS_SEND_TIMEOUT,
            what="global WebSocket",
        )

        if disconnected:
            async with self._global_lock:
                for conn in disconnected:
                    self._global_connections.discard(conn)


# Global connection manager instance
manager = ConnectionManager()
