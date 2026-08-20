"""AdaptiveCapabilityRouter — compose classify → constrain → score → (optional bandit).

Implements the ACR routing pipeline:

1. **Classify** — use ``task_model_router.classify_step`` to get the task
   category from the step description.
2. **Constrain** — apply the ``ConstraintChecker`` to filter candidates.
3. **Score** — apply the ``UtilityScorer`` to rank eligible candidates.
4. **Bandit** (optional) — apply Thompson sampling for explore/exploit.

Outputs an ordered candidate list for ``CascadeExecutor.call_with_cascade``.

Feature-flagged:
- ``WEEBOT_ENABLE_ACR`` — master switch (default OFF in P1).
- ``WEEBOT_ACR_SHADOW`` — log-only mode (static router still executes).
- ``WEEBOT_ACR_BANDIT`` — bandit stage on/off (default OFF in P2).
"""

from __future__ import annotations

import logging

from weebot.application.services.routing.bandit import BanditSelector
from weebot.application.services.routing.constraint_checker import ConstraintChecker
from weebot.application.services.routing.utility_scorer import UtilityScorer
from weebot.application.services.task_model_router import classify_step, model_for_step
from weebot.config.capability_profiles import get_all_profiles, get_requirement
from weebot.config.feature_flags import WEEBOT_ACR_BANDIT, WEEBOT_ACR_SHADOW, WEEBOT_ENABLE_ACR
from weebot.core.model_cascade_tracker import CascadeDecision, CascadeOutcome, ModelCascadeTracker

logger = logging.getLogger(__name__)


class AdaptiveCapabilityRouter:
    """Closed-loop model router: classify → constrain → score → (bandit).

    Args:
        tracker: Optional ``ModelCascadeTracker`` for live telemetry.
        is_tripped: Optional callback ``(model_id) -> bool`` for the
            constraint checker's availability gate.
        posterior_repo: Optional ``PosteriorRepository`` for the bandit's
            durable belief store.
        force_acr: When True, skip the ``WEEBOT_ENABLE_ACR`` flag check.
            Used for testing.
        force_bandit: When True, skip the ``WEEBOT_ACR_BANDIT`` flag check.
            Used for testing.
    """

    def __init__(
        self,
        tracker: ModelCascadeTracker | None = None,
        is_tripped=None,  # Callable[[str], bool] | None
        posterior_repo=None,  # PosteriorRepository | None
        force_acr: bool = False,
        force_bandit: bool = False,
    ) -> None:
        self._tracker = tracker
        self._acr_enabled = force_acr or WEEBOT_ENABLE_ACR
        self._shadow_mode = WEEBOT_ACR_SHADOW
        self._bandit_enabled = force_bandit or (self._acr_enabled and WEEBOT_ACR_BANDIT)
        self._posterior_repo = posterior_repo
        self._checker = ConstraintChecker(is_tripped=is_tripped)
        self._scorer = UtilityScorer(tracker=tracker)
        self._bandit = BanditSelector() if (force_bandit or WEEBOT_ACR_BANDIT) else None

    # ── Routing ─────────────────────────────────────────────────────

    def route(
        self,
        description: str,
        candidates: list[str] | None = None,
        posteriors: dict[str, tuple[float, float]] | None = None,
    ) -> list[str]:
        """Return an ordered list of model IDs for *description*.

        When ACR is disabled (or an error occurs), returns the static
        ``model_for_step(description)`` as a single-element list.

        Args:
            description: The step description to route.
            candidates: Optional candidate pool.  When ``None``, uses all
                registered models from the quality profile registry.
            posteriors: Optional pre-loaded posteriors ``{model_id: (alpha, beta)}``
                for the bandit stage.  Only used when the bandit is enabled.

        Returns:
            Ordered list of model IDs (highest utility first).  Always at
            least one entry (the static fallback).
        """
        # ── Static fallback path (ACR disabled) ─────────────────
        if not self._acr_enabled:
            return [model_for_step(description)]

        try:
            # 1. Classify
            category = classify_step(description)
            requirement = get_requirement(category)
            logger.debug(
                "ACR: classified '%s' as %s",
                description[:60],
                category.value,
                extra={"acr_event": "classify", "category": category.value},
            )

            # 2. Build candidate pool
            if candidates is None:
                candidates = list(get_all_profiles().keys())
            if not candidates:
                logger.warning("ACR: empty candidate pool — falling back to static")
                return [model_for_step(description)]

            # 3. Constrain
            eligible = self._checker.eligible(candidates, requirement)
            if not eligible:
                logger.warning(
                    "ACR: all %d candidates failed constraints for %s — " "falling back to static",
                    len(candidates),
                    category.value,
                )
                return [model_for_step(description)]

            # 4. Score
            scored = self._scorer.score(eligible, category)

            # 5. Bandit (Thompson sampling, optional)
            bandit_used = False
            if self._bandit and self._bandit_enabled and len(scored) > 1:
                bandit_used = True
                utility_scores = {r.model_id: r.score for r in scored}
                premium_models = {"x-ai/grok-4.3:thinking", "z-ai/glm-5.2:thinking"}
                scored = self._bandit.select(
                    candidates=scored,
                    category=category.value,
                    posteriors=posteriors,
                    utility_scores=utility_scores,
                    premium_models=premium_models,
                )
                logger.debug(
                    "ACR (bandit): %s → top-3: %s",
                    category.value,
                    [f"{r.model_id}={r.score}" for r in scored[:3]],
                    extra={"acr_event": "bandit", "category": category.value},
                )

            ordered = [r.model_id for r in scored]

            # 6. Structured decision log
            logger.info(
                "ACR decision: category=%s selected=%s candidates=%d explore=%s",
                category.value,
                ordered[0] if ordered else "none",
                len(scored),
                bandit_used,
                extra={
                    "acr_event": "decision",
                    "category": category.value,
                    "selected": ordered[0] if ordered else None,
                    "candidates": ordered,
                    "scores": {r.model_id: r.score for r in scored},
                    "explore": bandit_used,
                    "description": description[:100],
                },
            )

            # 7. Shadow mode: log ACR choice but return static model
            if self._shadow_mode:
                logger.info(
                    "ACR (shadow): %s → %s",
                    category.value,
                    ordered[:3],
                    extra={
                        "acr_event": "shadow",
                        "category": category.value,
                        "acr_choice": ordered,
                    },
                )
                return [model_for_step(description)]

            return ordered

        except Exception as exc:
            logger.exception("ACR routing failed: %s", exc)
            return [model_for_step(description)]

    # ── Outcome recording ──────────────────────────────────────────

    def record_cascade_outcome(self, decision: CascadeDecision) -> None:
        """Translate a ``CascadeDecision`` into a bandit reward and record it.

        Reward logic (hard signals only, per plan §1.3):
        - SUCCESS outcome → success (True)
        - FAILED or CIRCUIT_OPEN → failure (False)
        """
        if not self._tracker or not self._posterior_repo or not self._bandit:
            return  # bandit learning not wired

        success = decision.outcome == CascadeOutcome.SUCCESS
        self._bandit.record_outcome(
            category=decision.task_category,
            model_id=decision.model_name,
            success=success,
            posterior_repo=self._posterior_repo,
        )
        logger.debug(
            "ACR outcome: %s/%s → %s",
            decision.task_category,
            decision.model_name,
            "success" if success else "failure",
        )

    # ── Utilities ──────────────────────────────────────────────────

    @property
    def static_model(self, description: str) -> str:
        """Return the static model for *description* (same as ``model_for_step``)."""
        return model_for_step(description)
