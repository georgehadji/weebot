"""Circuit breaker for model-level and agent-level failure isolation.

Implements the standard CLOSED → OPEN → HALF_OPEN state machine with
per-entity tracking, asyncio-safe locking, and optional EventBroker
integration for publishing state-change events.

The public API mirrors :class:`ExecApprovalPolicy` — call
``evaluate(entity_id)`` to get a typed :class:`BreakerResult`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Public types
# ------------------------------------------------------------------


class BreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Healthy — all requests pass through
    OPEN = "open"  # Failing — all requests rejected immediately
    HALF_OPEN = "half_open"  # Probing — one request allowed to test recovery


@dataclass
class BreakerResult:
    """Result of a circuit breaker evaluation (mirrors ApprovalResult)."""

    entity_id: str
    allowed: bool
    state: BreakerState
    reason: str = ""
    failure_count: int = 0
    last_failure_time: float = 0.0


# ------------------------------------------------------------------
# Internal state
# ------------------------------------------------------------------


@dataclass
class _BreakerEntry:
    """Per-entity circuit breaker state."""

    state: BreakerState = BreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.monotonic)


# ------------------------------------------------------------------
# CircuitBreaker
# ------------------------------------------------------------------


class CircuitBreaker:
    """Per-entity circuit breaker with optional EventBroker integration.

    Supports both model-level and agent-level failure isolation.

    Args:
        failure_threshold: Consecutive failures before CLOSED → OPEN.
        cooldown_seconds: Seconds before OPEN → HALF_OPEN transition.
        success_threshold: Consecutive successes in HALF_OPEN to close.
        event_broker: Optional :class:`EventBroker` for state-change events.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        success_threshold: int = 1,
        event_broker: Optional[Any] = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")

        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._success_threshold = success_threshold
        self._event_broker = event_broker
        self._breakers: Dict[str, _BreakerEntry] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, entity_id: str) -> _BreakerEntry:
        if entity_id not in self._breakers:
            self._breakers[entity_id] = _BreakerEntry()
        return self._breakers[entity_id]

    async def _publish_state_change(
        self,
        entity_id: str,
        old_state: BreakerState,
        new_state: BreakerState,
    ) -> None:
        _log.info(
            "CircuitBreaker %s: %s -> %s",
            entity_id,
            old_state.value,
            new_state.value,
        )
        if self._event_broker is not None:
            await self._event_broker.publish(
                "circuit_breaker_state_change",
                entity_id,
                {
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "entity_id": entity_id,
                },
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(self, entity_id: str) -> BreakerResult:
        """Evaluate whether a request to *entity_id* should proceed.

        Handles the automatic OPEN → HALF_OPEN transition when the
        cooldown period has elapsed.

        Returns:
            :class:`BreakerResult` with ``allowed=True/False``.
        """
        async with self._lock:
            entry = self._get_or_create(entity_id)
            now = time.monotonic()

            if entry.state == BreakerState.CLOSED:
                return BreakerResult(
                    entity_id=entity_id,
                    allowed=True,
                    state=BreakerState.CLOSED,
                    failure_count=entry.failure_count,
                )

            if entry.state == BreakerState.OPEN:
                elapsed = now - entry.last_state_change
                if elapsed >= self._cooldown_seconds:
                    # Transition to HALF_OPEN
                    old = entry.state
                    entry.state = BreakerState.HALF_OPEN
                    entry.success_count = 0
                    entry.last_state_change = now
                    await self._publish_state_change(
                        entity_id, old, BreakerState.HALF_OPEN
                    )
                    return BreakerResult(
                        entity_id=entity_id,
                        allowed=True,
                        state=BreakerState.HALF_OPEN,
                        reason="Probing after cooldown",
                        failure_count=entry.failure_count,
                    )
                remaining = self._cooldown_seconds - elapsed
                return BreakerResult(
                    entity_id=entity_id,
                    allowed=False,
                    state=BreakerState.OPEN,
                    reason=f"Circuit open, {remaining:.1f}s until probe",
                    failure_count=entry.failure_count,
                    last_failure_time=entry.last_failure_time,
                )

            # HALF_OPEN — allow probe request
            return BreakerResult(
                entity_id=entity_id,
                allowed=True,
                state=BreakerState.HALF_OPEN,
                reason="Probe request allowed",
                failure_count=entry.failure_count,
            )

    async def record_success(self, entity_id: str) -> None:
        """Record a successful request for *entity_id*."""
        async with self._lock:
            entry = self._get_or_create(entity_id)

            if entry.state == BreakerState.HALF_OPEN:
                entry.success_count += 1
                if entry.success_count >= self._success_threshold:
                    old = entry.state
                    entry.state = BreakerState.CLOSED
                    entry.failure_count = 0
                    entry.success_count = 0
                    entry.last_state_change = time.monotonic()
                    await self._publish_state_change(
                        entity_id, old, BreakerState.CLOSED
                    )
            elif entry.state == BreakerState.CLOSED:
                # Reset failure count on success
                entry.failure_count = 0

    async def record_failure(self, entity_id: str) -> None:
        """Record a failed request for *entity_id*."""
        async with self._lock:
            entry = self._get_or_create(entity_id)
            now = time.monotonic()
            entry.failure_count += 1
            entry.last_failure_time = now

            if entry.state == BreakerState.HALF_OPEN:
                # Probe failed — revert to OPEN
                old = entry.state
                entry.state = BreakerState.OPEN
                entry.last_state_change = now
                await self._publish_state_change(
                    entity_id, old, BreakerState.OPEN
                )
            elif entry.state == BreakerState.CLOSED:
                if entry.failure_count >= self._failure_threshold:
                    old = entry.state
                    entry.state = BreakerState.OPEN
                    entry.last_state_change = now
                    await self._publish_state_change(
                        entity_id, old, BreakerState.OPEN
                    )

    # ------------------------------------------------------------------
    # Inspection / manual override
    # ------------------------------------------------------------------

    def get_state(self, entity_id: str) -> BreakerState:
        """Get the current state for *entity_id* (sync, for inspection)."""
        entry = self._breakers.get(entity_id)
        return entry.state if entry else BreakerState.CLOSED

    def get_all_states(self) -> Dict[str, BreakerState]:
        """Snapshot of all tracked entity states."""
        return {eid: e.state for eid, e in self._breakers.items()}

    async def reset(self, entity_id: str) -> None:
        """Manually reset *entity_id* to CLOSED."""
        async with self._lock:
            if entity_id in self._breakers:
                old = self._breakers[entity_id].state
                self._breakers[entity_id] = _BreakerEntry()
                if old != BreakerState.CLOSED:
                    await self._publish_state_change(
                        entity_id, old, BreakerState.CLOSED
                    )
