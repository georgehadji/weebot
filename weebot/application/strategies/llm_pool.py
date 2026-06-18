"""Global LLM concurrency pool — bounds concurrent API requests across all sessions.

Without this, every PlanActFlow session fires parallel LLM calls simultaneously
(via _call_with_cascade's Phase 1).  Under 10× load, 30+ concurrent sessions
could produce 90+ parallel API requests, overwhelming both the network layer
and OpenRouter rate limits.

The pool uses an asyncio.Semaphore to cap concurrent in-flight LLM calls.
Every LLM adapter acquires a token before making a request and releases it
afterward.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class LLMPool:
    """Bounded pool for concurrent LLM calls across all sessions.

    Usage in an LLM adapter::

        pool = LLMPool(max_concurrent=12)
        async with pool:
            resp = await provider.chat(...)
    """

    def __init__(self, max_concurrent: int = 12) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max = max_concurrent
        self._available = max_concurrent  # Tracked counter (avoids private _value attr)

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def available(self) -> int:
        """Number of available concurrency slots (exact, no race)."""
        return self._available

    async def __aenter__(self) -> "LLMPool":
        """Acquire a concurrency slot, waiting if all slots are in use.

        Raises asyncio.TimeoutError if not acquired within 120 seconds.
        """
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=120.0)
        except asyncio.TimeoutError:
            logger.error(
                "LLMPool timeout: all %d slots busy for 120s — possible deadlock",
                self._max,
            )
            raise
        self._available -= 1
        return self

    async def __aexit__(self, *args: object) -> None:
        """Release the concurrency slot."""
        self._semaphore.release()
        self._available += 1
