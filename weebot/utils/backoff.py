"""Exponential backoff retry utility (ported from OpenClaw gateway client)."""
from __future__ import annotations
import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional


@dataclass
class BackoffConfig:
    delays: List[float] = field(default_factory=lambda: [1, 2, 4, 8, 15, 30, 60])
    max_delay: Optional[float] = None
    jitter: float = 0.25
    """Fraction of delay to add as random jitter (0.25 → ±25%).
    Prevents thundering-herd when many callers fail simultaneously."""
    retryable: Optional[Callable[[Exception], bool]] = None
    """Optional predicate. Return False to re-raise immediately (circuit-breaker).
    When None, all exceptions are retried (previous behaviour)."""

    def __post_init__(self) -> None:
        if self.max_delay is not None:
            self.delays = [min(d, self.max_delay) for d in self.delays]


class RetryWithBackoff:
    """
    Async retry helper with configurable exponential backoff.

    Usage:
        retry = RetryWithBackoff()
        result = await retry.call(my_async_fn, arg1, arg2)

    Resets the delay index to 0 on a successful call.
    Non-retryable exceptions (per config.retryable) are re-raised immediately.
    """

    def __init__(self, config: Optional[BackoffConfig] = None) -> None:
        self._config = config or BackoffConfig()
        self._delay_index: int = 0

    async def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Call fn, retrying with backoff on each failure. Raises last exception after all retries."""
        last_exc: Optional[Exception] = None
        # Total attempts = number of delays + 1 (one initial try)
        attempts = len(self._config.delays) + 1

        for attempt in range(attempts):
            try:
                result = await fn(*args, **kwargs)
                self._delay_index = 0   # reset on success
                return result
            except Exception as exc:
                # Circuit-breaker: re-raise immediately if not retryable.
                if self._config.retryable is not None and not self._config.retryable(exc):
                    raise
                last_exc = exc
                if attempt < len(self._config.delays):
                    base = self._config.delays[attempt]
                    delay = base * (1.0 + random.random() * self._config.jitter)
                    self._delay_index = attempt + 1
                    await asyncio.sleep(delay)

        raise last_exc
