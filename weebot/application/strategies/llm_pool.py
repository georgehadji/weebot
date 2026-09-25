"""Global LLM concurrency pool — bounds concurrent API requests across all sessions.

Without this, every PlanActFlow session fires parallel LLM calls simultaneously
(via the cascade's Phase 1 probes). Under 10x load, 30+ concurrent sessions
could produce 90+ parallel API requests, overwhelming both the network layer
and OpenRouter rate limits.

The pool uses an asyncio.Semaphore to cap concurrent in-flight LLM calls.

History, because it explains the shape. This class was registered in the
container at WP-8 and then never passed to anything: ``CascadeExecutor``
accepted an ``llm_pool`` argument that no construction site supplied, so the
bounded branch of its guard never ran, and an audit document recorded the bound
as wired and verified. Phase 1.3 of
``tasks/specs/arch_audit_2026_09_remediation_plan.md`` wires it. Two things
had to change first, and both were invisible only because nothing had ever
contended the semaphore:

1. **Saturation raises its own error.** The acquire timeout used to raise
   ``TimeoutError``, which the cascade catches as "this model timed out". A
   full local pool would have been recorded as a failure of whichever healthy
   model happened to be next, walked the whole cascade, and ended the step in
   ``AllModelsTrippedError`` -- local load reported as every provider down.

2. **One semaphore per event loop.** ``asyncio.Semaphore`` binds to the first
   loop that has to wait on it; a second loop then fails with ``RuntimeError``
   the moment it contends. The pool is a process-wide DI singleton, and this
   process runs more than one loop (pytest, and background work that calls
   ``asyncio.run`` in threads). So the bound is per loop. In the web server
   there is one loop, which makes it per process -- the case it exists for.
"""

from __future__ import annotations

import asyncio
import logging
import weakref

from weebot.domain.exceptions import LLMCapacityExhaustedError

logger = logging.getLogger(__name__)

# Generous on purpose. The old hardcoded 120s had never executed in
# production, and a queued call now waits for a slot without that wait
# counting against the model's own timeout -- so this only has to cover how
# long it is reasonable to queue, not how long a model may take. Tune it from
# measurements; do not tighten it on a guess.
DEFAULT_ACQUIRE_TIMEOUT_S = 300.0


class LLMPool:
    """Bounded pool for concurrent LLM calls.

    Usage::

        pool = LLMPool(max_concurrent=12)
        async with pool:
            resp = await provider.chat(...)

    Raises :class:`LLMCapacityExhaustedError` if no slot frees up within
    ``acquire_timeout`` seconds.
    """

    def __init__(
        self,
        max_concurrent: int = 12,
        acquire_timeout: float = DEFAULT_ACQUIRE_TIMEOUT_S,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        self._max = max_concurrent
        self._acquire_timeout = acquire_timeout
        # Keyed weakly so a finished loop takes its semaphore with it.
        self._semaphores: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Semaphore
        ] = weakref.WeakKeyDictionary()
        self._in_use: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, int] = (
            weakref.WeakKeyDictionary()
        )

    @property
    def max_concurrent(self) -> int:
        return self._max

    @property
    def acquire_timeout(self) -> float:
        return self._acquire_timeout

    @property
    def available(self) -> int:
        """Free slots on the running loop (``max_concurrent`` if none has run)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._max
        return self._max - self._in_use.get(loop, 0)

    def _semaphore(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]:
        loop = asyncio.get_running_loop()
        sem = self._semaphores.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self._max)
            self._semaphores[loop] = sem
        return loop, sem

    async def __aenter__(self) -> LLMPool:
        """Acquire a slot, waiting up to ``acquire_timeout`` seconds."""
        loop, sem = self._semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self._acquire_timeout)
        except TimeoutError:
            logger.error(
                "LLMPool: all %d slots busy for %.0fs -- refusing the call rather "
                "than charging the wait to a model",
                self._max,
                self._acquire_timeout,
            )
            raise LLMCapacityExhaustedError(
                f"All {self._max} LLM concurrency slots stayed busy for "
                f"{self._acquire_timeout:.0f}s"
            ) from None
        self._in_use[loop] = self._in_use.get(loop, 0) + 1
        return self

    async def __aexit__(self, *args: object) -> None:
        """Release the slot on the loop that acquired it."""
        loop, sem = self._semaphore()
        self._in_use[loop] = self._in_use.get(loop, 1) - 1
        sem.release()
