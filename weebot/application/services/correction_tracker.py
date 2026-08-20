"""CorrectionTracker — surfaces recurring output-correction patterns.

Implements ICM's edit-source principle (paper §6.3): "Editing the output
fixes this run. Editing the source fixes every future run." This service
records the delta each time a step's output is replaced after a failed or
unverified attempt. When the same kind of correction recurs across
PATTERN_THRESHOLD records, it returns the triggering record so the caller
can surface a source-level fix (e.g. a behavioral rule — see
PlanActFlow's CorrectionPatternDetected handling).

Classification mirrors BehavioralLearner's LLM-with-heuristic-fallback
strategy: an LLM call when available (accurate, costs tokens), a cheap
length-ratio heuristic otherwise (free, coarse).
"""

from __future__ import annotations

import logging
from typing import Any

from weebot.config.constants import MAX_TOKENS_TINY, TEMPERATURE_PRECISE
from weebot.domain.models.correction import CorrectionRecord
from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = frozenset({"tone", "format", "scope", "accuracy", "missing_info"})

# Length-ratio bands for heuristic classification (corrected / original).
_SCOPE_SHRINK_RATIO = 0.7  # corrected is significantly shorter → over-scoped original
_MISSING_INFO_GROW_RATIO = 1.5  # corrected is significantly longer → original was thin


class CorrectionTracker:
    """Tracks recurring output corrections across a session/state repo.

    Args:
        state_repo: Persistence port exposing save_correction_record,
            count_corrections_by_category, get_correction_patterns.
        llm: Optional LLMPort for correction classification. Falls back
            to a length-ratio heuristic when omitted or when the call fails.
    """

    PATTERN_THRESHOLD = 3

    def __init__(self, state_repo: Any, llm: Any | None = None) -> None:
        self._state_repo = state_repo
        self._llm = llm

    async def record_correction(
        self, session_id: str, step: Step, original_output: str, corrected_output: str
    ) -> CorrectionRecord | None:
        """Record a correction; return the record if its category just hit threshold.

        Returns None while the category's count remains below
        ``PATTERN_THRESHOLD`` — this is the common case. Returns the
        triggering ``CorrectionRecord`` the moment the count reaches the
        threshold, so callers emit exactly one pattern-detected signal per
        threshold crossing rather than once per record.
        """
        category = await self._classify_correction(original_output, corrected_output)
        record = CorrectionRecord(
            session_id=session_id,
            step_id=step.id,
            step_description=step.description,
            original_output=original_output[:500],
            corrected_output=corrected_output[:500],
            correction_category=category,
        )
        await self._state_repo.save_correction_record(record)

        count = await self._state_repo.count_corrections_by_category(category)
        if count == self.PATTERN_THRESHOLD:
            logger.info(
                "Recurring correction pattern detected: category=%s count=%d", category, count
            )
            return record
        return None

    async def get_recurring_patterns(self, min_count: int = 3) -> list[dict]:
        """Return correction categories whose count meets or exceeds *min_count*."""
        return await self._state_repo.get_correction_patterns(min_count)

    # ── Classification ──────────────────────────────────────────────

    async def _classify_correction(self, original: str, corrected: str) -> str:
        if self._llm is not None:
            try:
                return await self._classify_with_llm(original, corrected)
            except Exception as exc:
                logger.warning("LLM correction classification failed: %s", exc)
        return self._classify_heuristic(original, corrected)

    async def _classify_with_llm(self, original: str, corrected: str) -> str:
        prompt = (
            f"Original output:\n{original[:400]}\n\n"
            f"Corrected output:\n{corrected[:400]}\n\n"
            "Classify the kind of correction in ONE word: "
            "tone, format, scope, accuracy, or missing_info.\n"
            "Answer:"
        )
        response = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You classify edits between two text versions into one category word.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=MAX_TOKENS_TINY,
            temperature=TEMPERATURE_PRECISE,
        )
        category = response.content.strip().strip('"').strip("'").lower()
        if category not in _VALID_CATEGORIES:
            return self._classify_heuristic(original, corrected)
        return category

    @staticmethod
    def _classify_heuristic(original: str, corrected: str) -> str:
        """Length-ratio classification when no LLM is configured.

        Coarse by design — a free pre-filter, not a precise diff. Distinguishes
        significant shrink (over-scoped originals) and significant growth
        (under-specified originals) from same-size rewrites (content fixes,
        bucketed as "accuracy").
        """
        original_len = max(len(original), 1)
        ratio = len(corrected) / original_len
        if ratio < _SCOPE_SHRINK_RATIO:
            return "scope"
        if ratio > _MISSING_INFO_GROW_RATIO:
            return "missing_info"
        return "accuracy"
