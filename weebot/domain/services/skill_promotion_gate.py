"""SkillPromotionGate — a chain-of-verification veto on candidate -> trusted.

Live use counting promotes a candidate after enough passing sessions
(``RecordSkillUseHandler``). This gate never promotes; it only blocks a promotion
whose skill makes claims that chain of verification contradicts.

- Contradicted (score below ``verify_threshold``): vetoed, the skill stays a candidate.
- Nothing checkable (a procedural skill yields no factual questions): passes.
- The check did not run (a provider error, an unparseable reply): vetoed, so an
  outage cannot let a skill through unchecked. A later use retries.

The old harness leg awaited ``HarnessMetricScorer.score(session_events=...)``,
a synchronous classmethod that takes a Session; it always raised and scored 0,
so it was dropped rather than repaired. A with-and-without A/B of the skill is
``skills compare`` (ComparisonRunner).
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.domain.models.skill import Skill, SkillPromotionResult

logger = logging.getLogger(__name__)

# ChainOfVerificationService.verify()'s reason when the text holds nothing to
# check (its NO_CLAIMS_REASON; a test keeps the two equal).
NOTHING_TO_CHECK = "no questions generated"


class SkillPromotionGate:
    """Veto a candidate skill's promotion when its claims do not hold.

    Args:
        chain_of_verification: An object with an async ``verify(query, response)``
            returning a result with ``verified``, ``reason``, ``score`` and
            ``corrected_response``.
        verify_threshold: Minimum share of consistent answers (default 0.7).
    """

    def __init__(self, chain_of_verification: Any, verify_threshold: float = 0.7) -> None:
        self._cov = chain_of_verification
        self._verify_threshold = verify_threshold

    async def evaluate(self, skill: Skill) -> SkillPromotionResult:
        """Return ``passed=False`` to keep *skill* a candidate."""
        try:
            result = await self._cov.verify(
                query=f"Evaluate skill: {skill.name}", response=skill.content[:2000]
            )
        except Exception as exc:
            logger.warning("SkillPromotionGate: verification failed for %s: %s", skill.name, exc)
            return SkillPromotionResult(
                skill_name=skill.name, passed=False, detail=f"verification failed: {exc}"
            )

        if not getattr(result, "verified", False):
            reason = getattr(result, "reason", "") or "unverified"
            nothing_to_check = reason == NOTHING_TO_CHECK
            return SkillPromotionResult(
                skill_name=skill.name,
                passed=nothing_to_check,
                detail=f"not verified: {reason}",
            )

        score = float(getattr(result, "score", 0.0) or 0.0)
        return SkillPromotionResult(
            skill_name=skill.name,
            passed=score >= self._verify_threshold,
            verify_score=score,
            detail=f"verify={score:.2f} (threshold={self._verify_threshold})",
        )
