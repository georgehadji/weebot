"""SkillReviewGate — LLM-judged review gate promoting quarantined -> candidate.

Closes the loop that ``domain/models/skill.py``'s ``SkillReview`` model was
always shaped for but that had no producer: ``AutonomousSkillCreator``
(``autonomous_learning.py``) distils and saves skills as ``quarantined``,
``Skill.is_injectable`` only allows ``trusted``, and
``Skill.record_positive_use`` only promotes ``candidate`` -> ``trusted``.
Nothing previously moved a skill from ``quarantined`` to ``candidate``, so
every self-distilled skill was permanently unreachable.

This is the funnel's cheap first stage: an LLM sanity/safety/novelty check,
no task execution. The funnel's second, expensive stage — execution-verified
promotion from ``candidate`` to ``trusted`` — is a separate concern already
covered by ``Skill.record_positive_use``'s usage counter and, optionally,
``SkillPromotionGate``'s verification-gated path.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.skill_store_port import SkillStorePort
from weebot.application.services.skill_curator import _extract_keywords, _keyword_overlap
from weebot.config.constants import MAX_TOKENS_MODERATE, TEMPERATURE_DETERMINISTIC
from weebot.domain.models.skill import Skill, SkillReview

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM = (
    "You are a skill quality gate. You review a single candidate skill "
    "(a reusable procedure distilled from an agent's own past task) before "
    "it is allowed to accrue trust. Score it honestly — most distilled "
    "skills are mediocre and should not pass.\n\n"
    "Respond with JSON only — no markdown fences, no commentary:\n"
    '{"coherence": 0.0-1.0, "value": 0.0-1.0, "safety": 0.0-1.0, '
    '"summary": "one sentence"}\n\n'
    "coherence: is this a clear, well-formed, actionable procedure?\n"
    "value: is this genuinely reusable and non-trivial, not a one-off fix "
    "or something any agent would already know to do?\n"
    "safety: does following this procedure carry no meaningful risk "
    "(no destructive defaults, no credential handling, no scope creep)?"
)


class SkillReviewGate:
    """Reviews a quarantined skill and decides candidate promotion.

    Args:
        llm: LLMPort for the structured review call.
        skill_store: Used to fetch existing skills for the novelty/similarity
            check. Comparison is against all currently stored skills — cheap
            at this subsystem's expected scale (tens to low hundreds of
            skills, not thousands); revisit if that stops being true.
        model: Model ID for the review call. Defaults to the cheap/budget
            model, matching SkillCurator's cost convention — this gate runs
            on every distillation, not on a schedule.
        coherence_threshold / value_threshold / safety_threshold: Minimum
            LLM-judged scores required to promote.
        similarity_threshold: Maximum keyword-Jaccard similarity against any
            existing skill before this one is rejected as a near-duplicate.
    """

    def __init__(
        self,
        llm: LLMPort,
        skill_store: Optional[SkillStorePort] = None,
        model: Optional[str] = None,
        coherence_threshold: float = 0.6,
        value_threshold: float = 0.5,
        safety_threshold: float = 0.8,
        similarity_threshold: float = 0.7,
    ) -> None:
        self._llm = llm
        self._skill_store = skill_store
        if model is None:
            from weebot.config.model_refs import MODEL_BUDGET
            model = MODEL_BUDGET
        self._model = model
        self._coherence_threshold = coherence_threshold
        self._value_threshold = value_threshold
        self._safety_threshold = safety_threshold
        self._similarity_threshold = similarity_threshold

    async def review(self, skill: Skill) -> SkillReview:
        """Review *skill* and return a SkillReview with the promotion verdict.

        Does not mutate *skill* or the store — the caller applies
        ``skill.with_trust("candidate")`` and persists it when
        ``review.promoted`` is True (see ``SkillReviewGate.apply``).
        """
        max_similarity, most_similar_to = await self._max_similarity(skill)
        if max_similarity >= self._similarity_threshold:
            return SkillReview(
                skill_name=skill.name,
                similarity=max_similarity,
                summary=f"Near-duplicate of existing skill '{most_similar_to}'.",
                recommendation="reject",
                promoted=False,
            )

        coherence, value, safety, summary = await self._llm_review(skill)

        passed = (
            coherence >= self._coherence_threshold
            and value >= self._value_threshold
            and safety >= self._safety_threshold
        )

        return SkillReview(
            skill_name=skill.name,
            coherence=coherence,
            value=value,
            similarity=max_similarity,
            safety=safety,
            summary=summary,
            recommendation="promote" if passed else "reject",
            promoted=passed,
        )

    async def apply(self, skill: Skill) -> tuple[Skill, SkillReview]:
        """Review *skill* and, on promotion, persist it as 'candidate'.

        Returns the (possibly updated) skill and the review that produced
        the decision. Safe to call on a skill that isn't 'quarantined' —
        review still runs, but promotion is only meaningful from that tier.
        """
        review = await self.review(skill)
        if not review.promoted:
            return skill, review

        promoted_skill = skill.with_trust("candidate")
        if self._skill_store is not None:
            try:
                await self._skill_store.save(promoted_skill)
                logger.info(
                    "Promoted skill '%s' quarantined -> candidate "
                    "(coherence=%.2f value=%.2f safety=%.2f similarity=%.2f)",
                    skill.name, review.coherence, review.value,
                    review.safety, review.similarity,
                )
            except Exception as exc:
                logger.warning(
                    "Reviewed and approved skill '%s' but failed to persist "
                    "promotion: %s", skill.name, exc,
                )
                return skill, review
        return promoted_skill, review

    # ── internals ────────────────────────────────────────────────────

    async def _max_similarity(self, skill: Skill) -> tuple[float, str]:
        """Return (max_jaccard_overlap, name) against all stored skills."""
        if self._skill_store is None:
            return 0.0, ""
        try:
            names = await self._skill_store.list_names()
        except Exception as exc:
            logger.debug("SkillReviewGate: could not list existing skills: %s", exc)
            return 0.0, ""

        target_kw = _extract_keywords(f"{skill.name} {skill.description} {skill.content}")
        best_score = 0.0
        best_name = ""
        for other_name in names:
            if other_name == skill.name:
                continue
            try:
                other = await self._skill_store.load(other_name)
            except Exception:
                continue
            if other is None:
                continue
            other_kw = _extract_keywords(f"{other.name} {other.description} {other.content}")
            overlap = _keyword_overlap(target_kw, other_kw)
            if overlap > best_score:
                best_score = overlap
                best_name = other_name
        return best_score, best_name

    async def _llm_review(self, skill: Skill) -> tuple[float, float, float, str]:
        """Call the LLM for structured coherence/value/safety scoring.

        Returns (0.0, 0.0, 0.0, reason) on any failure — a review that
        cannot be scored does not promote, it fails closed.
        """
        prompt = (
            f"Skill name: {skill.name}\n"
            f"Description: {skill.description}\n"
            f"Content:\n{skill.content[:2000]}"
        )
        try:
            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _REVIEW_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=self._model,
                temperature=TEMPERATURE_DETERMINISTIC,
                max_tokens=MAX_TOKENS_MODERATE,
            )
            raw = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.warning("SkillReviewGate: LLM review call failed for '%s': %s", skill.name, exc)
            return 0.0, 0.0, 0.0, f"review call failed: {exc}"

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("SkillReviewGate: no JSON in review response for '%s'", skill.name)
            return 0.0, 0.0, 0.0, "review response was not parseable JSON"
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as exc:
            logger.warning("SkillReviewGate: JSON parse error for '%s': %s", skill.name, exc)
            return 0.0, 0.0, 0.0, f"review JSON parse error: {exc}"

        def _clamped(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(data.get(key, 0.0))))
            except (TypeError, ValueError):
                return 0.0

        coherence = _clamped("coherence")
        value = _clamped("value")
        safety = _clamped("safety")
        summary = str(data.get("summary", ""))[:300]
        return coherence, value, safety, summary
