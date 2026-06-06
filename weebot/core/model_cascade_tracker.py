"""ModelCascadeTracker — thread-safe ring buffer of cascade decisions.

Records every model-cascade attempt (FREE → BUDGET → PREMIUM) with outcome,
latency, token count, and cost estimate.  Used by the cost dashboard, MCP
``weebot://costs`` resource, and web API.

Lives in ``core/`` so it can be imported without pulling in application or
infrastructure layers.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, List, Optional


class CascadeTier(str, Enum):
    """Model cost tier used in cascade routing."""
    FREE = "free"
    BUDGET = "budget"
    PREMIUM = "premium"


class CascadeOutcome(str, Enum):
    """Outcome of a cascade attempt at a given tier."""
    SUCCESS = "success"
    FAILED = "failed"             # API error, timeout, etc.
    CIRCUIT_OPEN = "circuit_open" # Circuit breaker prevented the attempt


@dataclass(frozen=True)
class CascadeDecision:
    """A single cascade routing decision record.

    Immutable — once recorded, never mutated.  Thread-safe by construction.
    """
    model_name: str
    tier: CascadeTier
    outcome: CascadeOutcome
    latency_ms: float
    token_count: int = 0
    cost_estimate: float = 0.0
    error_message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ModelCascadeTracker:
    """Thread-safe ring buffer of cascade routing decisions.

    Records every tier attempt during model cascading so operators can
    answer questions like:

    - "How often does the cascade fall through to PREMIUM?"
    - "What's the average latency per tier?"
    - "How much did we save by trying FREE/BUDGET first?"

    Usage::

        tracker = ModelCascadeTracker(max_decisions=500)
        tracker.record(CascadeDecision(
            model_name="deepseek-chat",
            tier=CascadeTier.FREE,
            outcome=CascadeOutcome.SUCCESS,
            latency_ms=234.5,
            token_count=1200,
            cost_estimate=0.0,
        ))

    Args:
        max_decisions: Maximum number of decisions to retain (default 500).
    """

    def __init__(self, max_decisions: int = 500) -> None:
        self._max = max_decisions
        self._buffer: Deque[CascadeDecision] = deque(maxlen=max_decisions)
        self._lock = threading.Lock()

    # ── Recording ─────────────────────────────────────────────────────

    def record(self, decision: CascadeDecision) -> None:
        """Record a cascade decision (newest-first in queries)."""
        with self._lock:
            self._buffer.appendleft(decision)

    # ── Querying ──────────────────────────────────────────────────────

    def recent(self, n: int = 50) -> List[CascadeDecision]:
        """Return up to *n* most recent decisions (newest first)."""
        with self._lock:
            return list(self._buffer)[:n]

    def summary(self) -> dict:
        """Return aggregate statistics for the current session.

        Returns a dict with:
        - ``total_decisions``: total decisions recorded
        - ``per_tier``: {tier: {success, failed, circuit_open, total}}
        - ``total_cost_estimate``: sum of cost estimates
        - ``avg_latency_ms``: mean latency across all decisions
        - ``cascade_hit_rate``: fraction where FREE or BUDGET succeeded
        """
        with self._lock:
            decisions = list(self._buffer)

        if not decisions:
            return {
                "total_decisions": 0,
                "per_tier": {},
                "total_cost_estimate": 0.0,
                "avg_latency_ms": 0.0,
                "cascade_hit_rate": 1.0,
            }

        per_tier: dict = {}
        total_cost = 0.0
        total_latency = 0.0
        cascade_hits = 0

        for d in decisions:
            tier_stats = per_tier.setdefault(
                d.tier.value,
                {"success": 0, "failed": 0, "circuit_open": 0, "total": 0},
            )
            tier_stats["total"] += 1
            if d.outcome == CascadeOutcome.SUCCESS:
                tier_stats["success"] += 1
                if d.tier in (CascadeTier.FREE, CascadeTier.BUDGET):
                    cascade_hits += 1
            elif d.outcome == CascadeOutcome.CIRCUIT_OPEN:
                tier_stats["circuit_open"] += 1
            else:
                tier_stats["failed"] += 1

            total_cost += d.cost_estimate
            total_latency += d.latency_ms

        n = len(decisions)
        return {
            "total_decisions": n,
            "per_tier": per_tier,
            "total_cost_estimate": round(total_cost, 6),
            "avg_latency_ms": round(total_latency / n, 1),
            "cascade_hit_rate": round(cascade_hits / n, 3) if n > 0 else 1.0,
        }

    def clear(self) -> None:
        """Remove all recorded decisions."""
        with self._lock:
            self._buffer.clear()
