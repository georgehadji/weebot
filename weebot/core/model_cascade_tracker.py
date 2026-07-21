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

    .. versionadded:: 0.4.0
       Fields *task_category*, *json_valid*, *tool_success*, *retries*,
       and *critic_score* added for Adaptive Capability Router (ACR).
       All are optional with safe defaults for backward compatibility.
    """
    model_name: str
    tier: CascadeTier
    outcome: CascadeOutcome
    latency_ms: float
    token_count: int = 0
    cost_estimate: float = 0.0
    error_message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # ── ACR enrichment (Phase P0) ───────────────────────────────────
    task_category: str = "general"
    json_valid: bool | None = None
    tool_success: bool | None = None
    retries: int = 0
    critic_score: float | None = None


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
        # Ring-buffer per (category, model) for per-category stats
        self._cat_buffer: Deque[CascadeDecision] = deque(maxlen=max_decisions)
        self._cat_lock = threading.Lock()

    # ── Recording ─────────────────────────────────────────────────────

    def record(self, decision: CascadeDecision) -> None:
        """Record a cascade decision (newest-first in queries)."""
        with self._lock:
            self._buffer.appendleft(decision)
        with self._cat_lock:
            self._cat_buffer.appendleft(decision)

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

    def per_category_stats(self) -> dict[str, dict[str, dict]]:
        """Return per-category, per-model aggregate statistics.

        Returns::

            {
                "coding": {
                    "deepseek/deepseek-v4-flash": {
                        "attempts": 12,
                        "successes": 10,
                        "failures": 2,
                        "success_rate": 0.833,
                        "mean_latency_ms": 234.5,
                        "mean_cost": 0.0012,
                    },
                    ...
                },
                ...
            }

        Thread-safe — operates on a snapshot copy of the ring buffer.
        """
        with self._cat_lock:
            decisions = list(self._cat_buffer)

        # Build nested dict: category → model → {counters}
        stats: dict[str, dict[str, dict]] = {}
        for d in decisions:
            cat_stats = stats.setdefault(d.task_category, {})
            model_stats = cat_stats.setdefault(d.model_name, {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "latency_sum": 0.0,
                "cost_sum": 0.0,
            })
            model_stats["attempts"] += 1
            if d.outcome == CascadeOutcome.SUCCESS:
                model_stats["successes"] += 1
            else:
                model_stats["failures"] += 1
            model_stats["latency_sum"] += d.latency_ms
            model_stats["cost_sum"] += d.cost_estimate

        # Convert sums to means for the final output
        result: dict[str, dict[str, dict]] = {}
        for category, models in stats.items():
            result[category] = {}
            for model_name, m in models.items():
                att = m["attempts"]
                result[category][model_name] = {
                    "attempts": att,
                    "successes": m["successes"],
                    "failures": m["failures"],
                    "success_rate": round(m["successes"] / att, 4) if att else 0.0,
                    "mean_latency_ms": round(m["latency_sum"] / att, 1) if att else 0.0,
                    "mean_cost": round(m["cost_sum"] / att, 8) if att else 0.0,
                }
        return result

    def clear(self) -> None:
        """Remove all recorded decisions."""
        with self._lock:
            self._buffer.clear()
        with self._cat_lock:
            self._cat_buffer.clear()
