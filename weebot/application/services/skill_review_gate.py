"""SkillReviewGate — LLM-based review that promotes quarantined skills to candidate.

Takes a quarantined skill, runs an LLM review evaluating:
- Coherence (is the skill well-structured?)
- Value (does it add meaningful capability?)
- Similarity (does it overlap with existing skills?)
- Safety (does it contain harmful instructions?)

On passing review, the skill's trust tier is changed from "quarantined"
to "candidate". On failure, the skill remains quarantined with a
review_notes field populated.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from weebot.domain.models.skill import Skill, SkillReview

logger = logging.getLogger(__name__)

_REVIEW_SYSTEM_PROMPT = """You are a skill reviewer. Evaluate the proposed skill on four axes:

1. **coherence** (0-1): Is the skill well-structured with clear instructions?
2. **value** (0-1): Does it add meaningful capability not already covered?
3. **similarity** (0-1): How similar is it to existing skills? (0 = unique, 1 = duplicate)
4. **safety** (0-1): Does the skill contain harmful or dangerous instructions? (0 = safe)

Respond with JSON: {"coherence": 0.0, "value": 0.0, "similarity": 0.0, "safety": 0.0, "summary": "...", "recommendation": "promote|reject"}

Promote when coherence >= 0.6, value >= 0.5, similarity < 0.8, safety >= 0.7.
"""


class SkillReviewGate:
    """Reviews quarantined skills and promotes to candidate on passing.

    Args:
        llm: An object with an async ``chat()`` method matching
            ``LLMPort``'s signature.
        model: Model identifier for the review call.
    """

    def __init__(self, llm, model: Optional[str] = None) -> None:
        self._llm = llm
        self._model = model

    async def review(self, skill: Skill, existing_names: list[str]) -> SkillReview:
        """Review a quarantined skill and return the review verdict.

        Args:
            skill: The skill to review (must have trust == "quarantined").
            existing_names: Names of already-registered skills for
                similarity context.

        Returns:
            A ``SkillReview`` with verdict, scores, and summary.
        """
        from weebot.domain.models.skill import SkillReview

        existing_text = ", ".join(existing_names[:20]) if existing_names else "(none)"

        prompt = (
            f"Skill name: {skill.name}\n"
            f"Description: {skill.description}\n"
            f"Body:\n{skill.content}\n\n"
            f"Existing skills: {existing_text}\n\n"
            "Evaluate and respond with JSON."
        )

        messages = [
            {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self._llm.chat(
                messages=messages,
                model=self._model,
                temperature=0.2,
                max_tokens=500,
            )
            data = json.loads(response.content or "{}")
        except Exception as exc:
            logger.warning("SkillReviewGate: LLM call failed: %s", exc)
            return SkillReview(
                skill_name=skill.name,
                coherence=0.0,
                value=0.0,
                similarity=0.0,
                safety=0.0,
                summary="Review failed (LLM error). Remains quarantined.",
                recommendation="reject",
                promoted=False,
            )

        coherence = float(data.get("coherence", 0))
        value = float(data.get("value", 0))
        similarity = float(data.get("similarity", 0))
        safety = float(data.get("safety", 0))
        summary = str(data.get("summary", ""))
        recommendation = str(data.get("recommendation", "reject"))

        promotes = (
            recommendation == "promote"
            and coherence >= 0.6
            and value >= 0.5
            and similarity < 0.8
            and safety >= 0.7
        )

        return SkillReview(
            skill_name=skill.name,
            coherence=coherence,
            value=value,
            similarity=similarity,
            safety=safety,
            summary=summary,
            recommendation=recommendation,
            promoted=promotes,
        )
