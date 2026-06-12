"""Circuit breaker for model-level and agent-level failure isolation.

Implements the standard CLOSED → OPEN → HALF_OPEN state machine with
per-entity tracking, asyncio-safe locking, and optional EventBroker
integration for publishing state-change events.

HARDEN Mode Additions:
- Jittered recovery to prevent thundering herd
- Staggered HALF_OPEN probes
- Recovery rate metrics

The public API mirrors :class:`ExecApprovalPolicy` — call
``evaluate(entity_id)`` to get a typed :class:`BreakerResult`.
"""
from __future__ import annotations

import asyncio
import logging
import random
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

    HARDEN Mode: Jittered recovery prevents thundering herd when services
    recover from outages.

    Args:
        failure_threshold: Consecutive failures before CLOSED → OPEN.
        cooldown_seconds: Seconds before OPEN → HALF_OPEN transition.
        success_threshold: Consecutive successes in HALF_OPEN to close.
        event_broker: Optional :class:`EventBroker` for state-change events.
        jitter_percent: Random variation in cooldown (0-1, default 0.2 = 20%).
        enable_stagger: Add random delay before HALF_OPEN probe.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        success_threshold: int = 1,
        event_broker: Optional[Any] = None,
        jitter_percent: float = 0.2,
        enable_stagger: bool = True,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")
        if not 0 <= jitter_percent <= 1:
            raise ValueError("jitter_percent must be between 0 and 1")

        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._success_threshold = success_threshold
        self._event_broker = event_broker
        self._jitter_percent = jitter_percent
        self._enable_stagger = enable_stagger
        
        self._breakers: Dict[str, _BreakerEntry] = {}
        self._lock = asyncio.Lock()
        
        # HARDEN: Metrics for monitoring
        self._state_changes = 0
        self._recovery_attempts = 0
        self._successful_recoveries = 0

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

    def _get_jittered_cooldown(self) -> float:
        """HARDEN: Get cooldown with random jitter to prevent thundering herd."""
        jitter = self._cooldown_seconds * self._jitter_percent
        return self._cooldown_seconds + random.uniform(-jitter, jitter)
    
    async def _maybe_stagger_probe(self) -> None:
        """HARDEN: Add random delay before HALF_OPEN probe."""
        if self._enable_stagger:
            # Random delay between 0-500ms
            delay = random.uniform(0, 0.5)
            await asyncio.sleep(delay)

    async def evaluate(self, entity_id: str) -> BreakerResult:
        """Evaluate whether a request to *entity_id* should proceed.

        Handles the automatic OPEN → HALF_OPEN transition when the
        cooldown period has elapsed.

        HARDEN: Uses jittered cooldown and staggered probes to prevent
        thundering herd during recovery.

        Returns:
            :class:`BreakerResult` with ``allowed=True/False``.
        """
        # Phase 1: dirty pre-check (no lock) to decide whether to stagger.
        # _maybe_stagger_probe() must NOT be called while the lock is held —
        # it sleeps for up to 500 ms and would block every other caller
        # (evaluate / record_success / record_failure) for that duration.
        # A dirty read here is intentional; the authoritative state check
        # happens in Phase 2 under the lock.
        #
        # Compute jittered cooldown ONCE so the dirty check and the
        # authoritative check use the same value — avoids wasted stagger
        # delay when the two calls return different random jitter.
        jittered_cooldown = self._get_jittered_cooldown()
        entry_snapshot = self._breakers.get(entity_id)
        if (entry_snapshot is not None
                and entry_snapshot.state == BreakerState.OPEN
                and (time.monotonic() - entry_snapshot.last_state_change
                     >= jittered_cooldown)):
            await self._maybe_stagger_probe()

        # Phase 2: authoritative check and state mutation under lock.
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

                if elapsed >= jittered_cooldown:
                    # Transition to HALF_OPEN (stagger was already applied above)
                    old = entry.state
                    entry.state = BreakerState.HALF_OPEN
                    entry.success_count = 0
                    entry.last_state_change = time.monotonic()
                    self._state_changes += 1
                    self._recovery_attempts += 1

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
                remaining = jittered_cooldown - elapsed
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
                    self._state_changes += 1
                    self._successful_recoveries += 1  # HARDEN: Track recovery
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
                self._state_changes += 1  # HARDEN: Track state change
                await self._publish_state_change(
                    entity_id, old, BreakerState.OPEN
                )
            elif entry.state == BreakerState.CLOSED:
                if entry.failure_count >= self._failure_threshold:
                    old = entry.state
                    entry.state = BreakerState.OPEN
                    entry.last_state_change = now
                    self._state_changes += 1  # HARDEN: Track state change
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

    # ------------------------------------------------------------------
    # Persistence — save/load breaker state to survive restarts
    # ------------------------------------------------------------------

    def persist_state(self, path: str | Path) -> None:
        """Save all breaker states to a JSON file.

        Args:
            path: File path to write state to (e.g. ``~/.weebot/breaker_state.json``).
        """
        import json as _json
        data = self.to_persistable()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(_json.dumps(data, indent=2))

    def restore_state(self, path: str | Path) -> bool:
        """Load breaker states from a JSON file.

        Args:
            path: File path to read state from.

        Returns:
            True if state was restored, False if file doesn't exist.
        """
        import json as _json
        p = Path(path)
        if not p.exists():
            return False
        try:
            data = _json.loads(p.read_text())
            self.load_from_persistable(data)
            return True
        except Exception:
            _log.warning("Failed to restore circuit breaker state from %s", path)
            return False

    def to_persistable(self) -> list[dict[str, Any]]:
        """Serialize all breaker states for storage.

        Returns list of dicts suitable for JSON serialization.
        `last_state_change` is converted from monotonic time to
        wall-clock offset so it survives restarts.
        """
        now = time.monotonic()
        states: list[dict[str, Any]] = []
        for entity_id, entry in self._breakers.items():
            states.append({
                "entity_id": entity_id,
                "state": entry.state.value,
                "failure_count": entry.failure_count,
                "success_count": entry.success_count,
                "last_failure_time": entry.last_failure_time,
                "last_state_change_offset": now - entry.last_state_change,
            })
        return states

    def load_from_persistable(self, states: list[dict[str, Any]]) -> None:
        """Restore breaker states from previously saved data.

        Args:
            states: List of state dicts as returned by ``to_persistable()``.
        """
        now = time.monotonic()
        for s in states:
            entry = _BreakerEntry(
                state=BreakerState(s["state"]),
                failure_count=s["failure_count"],
                success_count=s.get("success_count", 0),
                last_failure_time=s.get("last_failure_time", 0.0),
                last_state_change=now - s.get("last_state_change_offset", 0.0),
            )
            self._breakers[s["entity_id"]] = entry

    # ------------------------------------------------------------------
    # HARDEN: Metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get circuit breaker metrics for monitoring.
        
        Returns:
            Dict with recovery statistics and current state counts.
        """
        state_counts = {"CLOSED": 0, "OPEN": 0, "HALF_OPEN": 0}
        for entry in self._breakers.values():
            state_counts[entry.state.name] += 1
        
        recovery_rate = (
            self._successful_recoveries / self._recovery_attempts
            if self._recovery_attempts > 0 else 1.0
        )
        
        return {
            "tracked_entities": len(self._breakers),
            "state_counts": state_counts,
            "state_changes_total": self._state_changes,
            "recovery_attempts": self._recovery_attempts,
            "successful_recoveries": self._successful_recoveries,
            "recovery_rate": recovery_rate,
            "jitter_enabled": self._jitter_percent > 0,
            "jitter_percent": self._jitter_percent,
            "stagger_enabled": self._enable_stagger,
            "cooldown_seconds": self._cooldown_seconds,
        }
