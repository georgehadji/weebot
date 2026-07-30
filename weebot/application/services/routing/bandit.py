"""BanditSelector — Thompson-sampling bandit over (category, model) posteriors.

Uses Beta-Bernoulli Thompson sampling to balance exploration and exploitation
when selecting among eligible models for a given task category.

Integration with the ACR pipeline:

1. The ``UtilityScorer`` produces a deterministic ranking.
2. The bandit receives pre-loaded posteriors (loaded by the async caller
   before calling into the sync routing pipeline) and replaces the
   deterministic utility with a Thompson-blended score for exploration.
3. Pure-exploration models are only selected within the exploration budget.

Cold-start: posterior defaults to strong priors (α₀=5, β₀=1) so exploration
is minimised for obviously weak models.

Non-stationarity: exponential forgetting (γ=0.95) applied on every update
so silent model upgrades are re-learned.

Exploration budget: caps the fraction of selections that may choose a
non-top-utility model per category per window.
"""
from __future__ import annotations

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


class BanditSelector:
    """Thompson-sampling bandit for model selection.

    The bandit accepts pre-loaded posteriors (from the async caller) and
    works entirely synchronously in the routing hot path.

    Args:
        explore_fraction: Fraction of selections that may explore
            (default 0.1 = 10%).
        premium_explore_fraction: Stricter fraction for premium-tier models
            (default 0.05 = 5%).
        random_seed: Optional seed for reproducibility in tests.
    """

    def __init__(
        self,
        explore_fraction: float = 0.1,
        premium_explore_fraction: float = 0.05,
        random_seed: int | None = None,
    ) -> None:
        self._explore_frac = explore_fraction
        self._premium_explore_frac = premium_explore_fraction
        self._rng = random.Random(random_seed)
        # Per-category counters for budget tracking
        self._total_count: dict[str, int] = {}
        self._explore_count: dict[str, int] = {}

    # ── Public API ──────────────────────────────────────────────────

    def select(
        self,
        candidates: list,
        category: str,
        posteriors: dict[str, tuple[float, float]] | None = None,
        utility_scores: dict[str, float] | None = None,
        premium_models: set[str] | None = None,
    ) -> list:
        """Return *candidates* reordered by Thompson-blended score.

        When the bandit decides to exploit (within budget), returns the
        deterministic utility ranking unchanged.  When it decides to explore,
        blends a Thompson sample from the posterior into the score.

        Args:
            candidates: List of objects with ``.model_id`` and ``.score``.
            category: Task category string.
            posteriors: Pre-loaded dict ``{model_id: (alpha, beta)}``.
                When omitted or empty, falls back to prior (α₀=5, β₀=1).
            utility_scores: Optional override dict ``{model_id: score}``.
                When omitted, reads from candidate's ``.score``.
            premium_models: Set of model IDs with stricter exploration budget.

        Returns:
            Reordered list (same objects, new order).
        """
        if not candidates or len(candidates) <= 1:
            return candidates

        posteriors = posteriors or {}
        premium_models = premium_models or set()
        is_explore = self._should_explore(category)

        # Track budget
        self._total_count[category] = self._total_count.get(category, 0) + 1
        if is_explore:
            self._explore_count[category] = self._explore_count.get(category, 0) + 1

        scored: list[tuple[float, object]] = []
        for cand in candidates:
            model_id = cand.model_id
            utility = utility_scores.get(model_id, cand.score) if utility_scores else cand.score

            if is_explore:
                thompson = self._sample_thompson(
                    model_id,
                    posteriors.get(model_id, (5.0, 1.0)),
                )
                # Premium model dampening
                if model_id in premium_models:
                    blend_factor = min(self._premium_explore_frac / max(self._explore_frac, 0.01), 1.0)
                else:
                    blend_factor = 1.0
                blended = (1 - 0.3 * blend_factor) * utility + 0.3 * blend_factor * thompson
            else:
                blended = utility

            scored.append((blended, cand))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [cand for _, cand in scored]

    def record_outcome(
        self,
        category: str,
        model_id: str,
        success: bool,
        posterior_repo=None,
    ) -> None:
        """Record an outcome to the posterior repository (if available).

        This is a best-effort fire-and-forget call.  If the repository is
        not available, the outcome is silently dropped (the bandit still
        works with prior beliefs).

        Args:
            category: Task category string.
            model_id: The model that was used.
            success: Whether the step succeeded (hard signal).
            posterior_repo: Optional ``PosteriorRepository`` instance.
        """
        if posterior_repo is not None:
            try:
                import anyio
                anyio.from_thread.run(
                    posterior_repo.record_outcome, category, model_id, success,
                )
            except Exception:
                logger.debug("Bandit: failed to record outcome (non-blocking)")

    # ── Internal ────────────────────────────────────────────────────

    def _sample_thompson(
        self,
        model_id: str,
        posterior: tuple[float, float],
    ) -> float:
        """Draw a sample θ ∼ Beta(α, β) from the posterior.

        Uses the selector's own seeded generator (``self._rng``).  This was
        previously a staticmethod that built a fresh unseeded
        ``random.Random()``, so ``BanditSelector(random_seed=...)`` had no
        effect on Thompson sampling: results were irreproducible in
        production and the unit tests were quietly flaky, failing whenever a
        draw from a skewed posterior landed in the tail.

        Args:
            model_id: Model identifier (used for logging only).
            posterior: ``(alpha, beta)`` tuple — the Beta posterior params.

        Returns:
            A sample in [0, 1], or the posterior mean if sampling fails.
        """
        alpha, beta = posterior
        try:
            rng = self._rng
            gamma_a = rng.gammavariate(alpha, 1.0)
            gamma_b = rng.gammavariate(beta, 1.0)
            if gamma_a + gamma_b <= 0:
                return 0.5
            return gamma_a / (gamma_a + gamma_b)
        except Exception:
            return alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5

    def _should_explore(self, category: str) -> bool:
        """Determine if the current selection should explore.

        Uses a per-category explore probability that decays as the posterior
        converges (fewer explorations after ~100 pulls).
        """
        total = self._total_count.get(category, 0)
        if total == 0:
            return True
        explore_prob = self._explore_frac * max(0.0, 1.0 - total / 100.0)
        return self._rng.random() < explore_prob

    def get_budget_used(self, category: str) -> dict:
        """Return budget tracking stats for *category*."""
        total = self._total_count.get(category, 0)
        explored = self._explore_count.get(category, 0)
        return {
            "total": total,
            "explored": explored,
            "explore_rate": round(explored / total, 4) if total else 0.0,
        }

    def reset_budget(self, category: str | None = None) -> None:
        """Reset budget counters for *category* (or all if ``None``)."""
        if category is None:
            self._total_count.clear()
            self._explore_count.clear()
        else:
            self._total_count.pop(category, None)
            self._explore_count.pop(category, None)
