"""UtilityScorer — rank eligible models by expected utility.

Corrected math (per ACR Appendix A):

    U(m) = α · cap_match(m) + β · quality_live(m) − δ · cost_norm(m) − ε · lat_norm(m)

Key invariants enforced by this module:

- **Quality axes only** in ``cap_match`` — cost and latency never enter the
  cosine similarity.  They are separate penalty terms.
- **Hard constraints** are NOT scored here — they are handled by the
  ``ConstraintChecker`` before this scorer runs.
- **Cold-start fallback**: when no telemetry exists for ``(category, model)``,
  ``quality_live`` falls back to the benchmark-seeded ``ModelQualityProfile``
  axes (mean across all axes for the model).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from weebot.config.capability_profiles import get_profile, get_requirement
from weebot.config.model_registry import get_model_info
from weebot.core.model_cascade_tracker import ModelCascadeTracker
from weebot.domain.models.capability import TaskRequirement
from weebot.application.services.task_model_router import TaskCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteCandidate:
    """A scored model candidate with breakdown for observability."""

    model_id: str
    score: float
    cap_match: float
    quality_live: float
    cost_norm: float
    lat_norm: float


class UtilityScorer:
    """Score eligible models by expected utility.

    Uses the corrected utility function from ACR Appendix A:
    quality axes only in cosine, cost/latency as separate penalty terms.

    Args:
        tracker: Optional ``ModelCascadeTracker`` for live telemetry.
            When provided, ``quality_live`` uses observed success rates.
            When omitted, all quality comes from benchmark-seeded profiles.
    """

    def __init__(self, tracker: ModelCascadeTracker | None = None) -> None:
        self._tracker = tracker

    # ── Public API ──────────────────────────────────────────────────

    def score(self, candidates: list[str], category: TaskCategory) -> list[RouteCandidate]:
        """Score *candidates* and return them ranked by expected utility.

        Args:
            candidates: Model IDs to score (must already pass constraint check).
            category: The task category — determines the requirement vector
                and the telemetry partition to query.

        Returns:
            Sorted list of ``RouteCandidate``, highest utility first.
        """
        if not candidates:
            return []

        requirement = get_requirement(category)

        # Gather raw scores for each candidate
        scores: list[dict] = []
        for model_id in candidates:
            cap_match = self._compute_cap_match(model_id, requirement)
            quality_live = self._compute_quality_live(model_id, category, requirement)
            cost = self._compute_cost(model_id)
            latency = self._compute_latency(model_id, category)

            scores.append(
                {
                    "model_id": model_id,
                    "cap_match": cap_match,
                    "quality_live": quality_live,
                    "cost": cost,
                    "latency": latency,
                }
            )

        # Normalise cost and latency across the candidate set (min-max)
        costs = [s["cost"] for s in scores]
        lats = [s["latency"] for s in scores]
        cost_min, cost_max = min(costs), max(costs)
        lat_min, lat_max = min(lats), max(lats)

        coeff = requirement.utility_coeff
        alpha = coeff.get("alpha", 0.4)
        beta = coeff.get("beta", 0.3)
        delta = coeff.get("delta", 0.2)
        epsilon = coeff.get("epsilon", 0.1)

        results: list[RouteCandidate] = []
        for s in scores:
            cost_norm = self._minmax(s["cost"], cost_min, cost_max)
            lat_norm = self._minmax(s["latency"], lat_min, lat_max)

            u = (
                alpha * s["cap_match"]
                + beta * s["quality_live"]
                - delta * cost_norm
                - epsilon * lat_norm
            )

            results.append(
                RouteCandidate(
                    model_id=s["model_id"],
                    score=round(u, 4),
                    cap_match=round(s["cap_match"], 4),
                    quality_live=round(s["quality_live"], 4),
                    cost_norm=round(cost_norm, 4),
                    lat_norm=round(lat_norm, 4),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ── Internal scoring helpers ────────────────────────────────────

    def _compute_cap_match(self, model_id: str, requirement: TaskRequirement) -> float:
        """Cosine similarity between model quality axes and requirement weights.

        Only quality axes are compared — cost and latency are NOT part of
        this computation.  Returns 0.0 for zero-norm vectors.
        """
        profile = get_profile(model_id)
        if profile is None or not profile.axes:
            return 0.0

        weights = requirement.quality_weights

        # Build vectors over the union of axes present in profile and weights
        all_axes = set(profile.axes.keys()) | set(weights.keys())
        if not all_axes:
            return 0.0

        # Sort axes for deterministic ordering
        sorted_axes = sorted(all_axes, key=lambda a: a.value)

        vec_a = [profile.axes.get(axis, 0.0) for axis in sorted_axes]
        vec_b = [weights.get(axis, 0.0) for axis in sorted_axes]

        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)

    def _compute_quality_live(
        self, model_id: str, category: TaskCategory, requirement: TaskRequirement
    ) -> float:
        """Success rate for (category, model) from telemetry, or benchmark prior.

        Cold-start: when no telemetry is available, returns the mean of the
        model's profile axes weighted by the requirement weights.

        Returns a value in 0..1.
        """
        # Try telemetry first
        if self._tracker is not None:
            cat_stats = self._tracker.per_category_stats().get(category.value, {})
            model_stats = cat_stats.get(model_id)
            if model_stats and model_stats["attempts"] > 0:
                return model_stats["success_rate"]

        # Fallback to benchmark-derived prior quality
        # Mean of profile axes, weighted by requirement weights
        # (already in 0..10 range; normalise to 0..1)
        profile = get_profile(model_id)
        if profile is None or not profile.axes:
            return 0.5  # neutral fallback

        weights = requirement.quality_weights
        total_weight = 0.0
        weighted_sum = 0.0
        for axis, score in profile.axes.items():
            w = weights.get(axis, 0.5)  # moderate weight for unmatched axes
            weighted_sum += score * w
            total_weight += w

        if total_weight == 0.0:
            return sum(profile.axes.values()) / (len(profile.axes) * 10)

        return min(weighted_sum / (total_weight * 10), 1.0)

    def _compute_cost(self, model_id: str) -> float:
        """Cost estimate for this model (sum of input + output cost per token).

        Returns 0.0 if model info is not available.
        """
        info = get_model_info(model_id)
        if info is None:
            return 0.0
        return info.calculate_cost_per_1k_tokens()

    def _compute_latency(self, model_id: str, category: TaskCategory) -> float:
        """Mean latency from telemetry for (category, model), or 0.

        Returns 0.0 when no telemetry is available (lowest penalty).
        """
        if self._tracker is None:
            return 0.0
        cat_stats = self._tracker.per_category_stats().get(category.value, {})
        model_stats = cat_stats.get(model_id)
        if model_stats and model_stats["attempts"] > 0:
            return model_stats["mean_latency_ms"]
        return 0.0

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _minmax(value: float, lo: float, hi: float) -> float:
        """Min-max normalise *value* to [0, 1] over the range [lo, hi].

        Returns 0.5 when lo == hi (no variation).
        """
        if hi == lo:
            return 0.5
        return (value - lo) / (hi - lo)
