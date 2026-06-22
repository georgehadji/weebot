"""SkillPromotionGate — verification-gated promotion from candidate to trusted.

Requires:
- ``ChainOfVerificationService.verify()`` on the skill's claimed behavior
  with score >= 0.7
- ``HarnessMetricScorer.score()`` on a trial run with composite >= 0.6

Only when both thresholds are met is the skill's trust tier promoted
from "candidate" to "trusted", making it injectable into the live executor.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from weebot.domain.models.skill import Skill, SkillPromotionResult

logger = logging.getLogger(__name__)


class SkillPromotionGate:
    """Verification-gated promotion for candidate skills.

    Args:
        chain_of_verification: A ``ChainOfVerificationService``-like
            object with an async ``verify()`` method returning a result
            with ``score`` and ``corrected_response`` attributes.
        harness_scorer: A ``HarnessMetricScorer``-like object with an
            async ``score()`` method returning a ``HarnessMetrics``
            object with ``composite()`` method.
        verify_threshold: Minimum verification score (default 0.7).
        harness_threshold: Minimum harness composite score (default 0.6).
    """

    def __init__(
        self,
        chain_of_verification: Any,
        harness_scorer: Any,
        verify_threshold: float = 0.7,
        harness_threshold: float = 0.6,
    ) -> None:
        self._cov = chain_of_verification
        self._harness = harness_scorer
        self._verify_threshold = verify_threshold
        self._harness_threshold = harness_threshold

    async def evaluate(self, skill: Skill, trial_context: Optional[str] = None) -> SkillPromotionResult:
        """Evaluate a candidate skill and promote if thresholds are met.

        Args:
            skill: The skill to evaluate (must have trust == "candidate").
            trial_context: Optional context string for the harness trial.

        Returns:
            A ``SkillPromotionResult`` with pass/fail, scores, and details.
        """
        from weebot.domain.models.skill import SkillPromotionResult

        # ── Step 1: Chain of Verification ──────────────────────────
        verify_score = 0.0
        verify_detail = ""
        try:
            verify_result = await self._cov.verify(
                query=f"Evaluate skill: {skill.name}",
                response=skill.body[:2000],
            )
            verify_score = getattr(verify_result, "score", 0) or 0.0
            verify_detail = getattr(verify_result, "corrected_response", "") or ""
        except Exception as exc:
            logger.warning("SkillPromotionGate: CoVe failed for %s: %s", skill.name, exc)
            return SkillPromotionResult(
                skill_name=skill.name,
                passed=False,
                verify_score=0.0,
                harness_score=0.0,
                detail=f"Chain of verification failed: {exc}",
            )

        # ── Step 2: Harness trial ──────────────────────────────────
        harness_score = 0.0
        try:
            harness_result = await self._harness.score(
                session_events=[],
                task_result=trial_context or skill.description,
            )
            harness_score = harness_result.composite() if hasattr(harness_result, "composite") else 0.0
        except Exception as exc:
            logger.warning("SkillPromotionGate: Harness trial failed for %s: %s", skill.name, exc)
            harness_score = 0.0

        # ── Decision ───────────────────────────────────────────────
        passed = (
            verify_score >= self._verify_threshold
            and harness_score >= self._harness_threshold
        )

        detail_parts = [
            f"verify={verify_score:.2f} (threshold={self._verify_threshold})",
            f"harness={harness_score:.2f} (threshold={self._harness_threshold})",
        ]
        if verify_detail:
            detail_parts.append(f"CoVe detail: {verify_detail[:200]}")

        return SkillPromotionResult(
            skill_name=skill.name,
            passed=passed,
            verify_score=verify_score,
            harness_score=harness_score,
            detail="; ".join(detail_parts),
        )
