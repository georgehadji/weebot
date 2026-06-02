"""InMemorySteeringAdapter — queue-based SteeringPort for single-process use.

Each session gets an asyncio.Queue.  send() puts a message; poll()
gets it non-blocking.  Thread-safe for send() from a stdin listener
thread via call_soon_threadsafe.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from weebot.application.ports.steering_port import SteeringPort


class InMemorySteeringAdapter(SteeringPort):
    """Queue-based steering for CLI and single-process web servers."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[str]] = {}

    async def poll(self, session_id: str) -> Optional[str]:
        """Return the next pending steering message, or None."""
        q = self._queues.get(session_id)
        if q is None or q.empty():
            return None
        try:
            return q.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def send(self, session_id: str, message: str) -> None:
        """Queue a steering message.  Safe to call from any thread."""
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        await self._queues[session_id].put(message)

    def send_threadsafe(self, session_id: str, message: str) -> None:
        """Thread-safe variant for stdin listeners running in executor."""
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        self._queues[session_id].put_nowait(message)
