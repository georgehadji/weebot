"""ExactMatchScorer — normalized string comparison for QA benchmarks.

Compares the agent's final answer against the expected answer with:
- Case-insensitive comparison
- Whitespace normalization (strip, collapse)
- Punctuation removal
- Substring containment fallback

Returns 1.0 for exact match, 0.0 for no match.
"""
from __future__ import annotations

import re
from typing import Optional

from weebot.application.ports.scoring_port import ScoringPort
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip, collapse whitespace,
    remove punctuation."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


class ExactMatchScorer(ScoringPort):
    """ScoringPort implementation that uses normalized string comparison.

    Suitable for QA benchmarks (SearchQA, DocVQA) where the answer is a
    short text string and the evaluation metric is exact match.

    Supports an optional substring threshold: if the normalized answer
    contains the expected answer (or vice versa), it scores 0.5.
    """

    def __init__(self, use_substring_fallback: bool = True):
        self._use_substring = use_substring_fallback

    async def score(
        self,
        session: Session,
        expected_answer: Optional[str] = None,
    ) -> TrajectoryScored:
        """Score a completed session by comparing its final message
        against the expected answer."""
        # Extract the final assistant message
        final_content = ""
        for event in reversed(session.events):
            if event.type == "message" and getattr(event, "role", "") == "assistant":
                final_content = getattr(event, "message", "") or ""
                break

        score = 0.0
        failure_modes: list[str] = []
        success_patterns: list[str] = []

        if expected_answer is None:
            score = 0.5  # No expected answer — partial credit
            failure_modes.append("no_expected_answer")
        else:
            normalized_actual = _normalize(final_content)
            normalized_expected = _normalize(expected_answer)

            if normalized_actual == normalized_expected:
                score = 1.0
                success_patterns.append("exact_match")
            elif self._use_substring and (
                normalized_expected in normalized_actual
                or normalized_actual in normalized_expected
            ):
                score = 0.5
                failure_modes.append("partial_match_only")
            else:
                score = 0.0
                failure_modes.append("answer_mismatch")

        return TrajectoryScored(
            session_id=session.id,
            task_id=session.id,
            score=score,
            failure_modes=failure_modes,
            success_patterns=success_patterns,
            trajectory_summary=final_content[:500],
            harness="exact_match",
        )
