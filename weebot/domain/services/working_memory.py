"""Working memory key-value fact store per session."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from weebot.domain.models.event import FactDiscovered
from weebot.domain.ports import EventPublisher


class WorkingMemory:
    """Simple key-value store for session-scoped facts."""

    _MAX_SESSIONS = 1000

    def __init__(self, event_publisher: Optional[EventPublisher] = None) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._event_publisher = event_publisher

    async def set_fact(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._store:
            # Evict oldest session when at capacity
            if len(self._store) >= self._MAX_SESSIONS:
                oldest = next(iter(self._store))
                del self._store[oldest]
            self._store[session_id] = {}
        self._store[session_id][key] = value

        if self._event_publisher:
            # We record the discovery of a fact via a domain event
            event = FactDiscovered(
                session_id=session_id,
                key=key,
                value=value
            )
            await self._event_publisher.publish(
                event_type="fact_discovered",
                agent_id="working_memory",
                data=event.model_dump()
            )

    def get_fact(self, session_id: str, key: str, default: Any = None) -> Any:
        return self._store.get(session_id, {}).get(key, default)

    def get_facts(self, session_id: str) -> dict[str, Any]:
        return dict(self._store.get(session_id, {}))

    def clear_session(self, session_id: str) -> None:
        self._store.pop(session_id, None)
