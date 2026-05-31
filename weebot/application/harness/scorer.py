"""TaskScorer — multi-strategy scoring for benchmark tasks.

Scoring priority:
  1. custom_scorer from task's evaluate.py (if present)
  2. Session-status heuristic (COMPLETED=1.0, FAILED=0.0)
  3. Exact match against expected_answer (case-insensitive, stripped)
  4. Token-overlap Jaccard (no external dependencies)
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Optional

from weebot.domain.models.benchmark_task import WeebotTask
from weebot.domain.models.session import Session

logger = logging.getLogger(__name__)


class TaskScorer:
    """Stateless scorer for benchmark task sessions."""

    @staticmethod
    async def score(session: Session, task: WeebotTask, sample_idx: int = 0) -> float:
        """Score *session* against *task.samples[sample_idx]*.

        Returns a float in [0.0, 1.0].
        """
        expected: Optional[str] = None
        if sample_idx < len(task.samples):
            expected = task.samples[sample_idx].expected_answer

        # 1. Custom scorer
        if task.custom_scorer is not None:
            try:
                result = task.custom_scorer(session, expected)
                if inspect.isawaitable(result):
                    result = await result
                return float(result)
            except Exception as exc:
                logger.warning("custom_scorer raised %s — falling back", exc)

        # 2. Status heuristic (when no expected answer)
        if not expected:
            status_name = getattr(session.status, "name", str(session.status))
            if status_name == "COMPLETED":
                return 1.0
            if status_name == "FAILED":
                return 0.0
            return 0.5

        actual = TaskScorer._extract_answer(session)
        if actual is None:
            return 0.0

        # 3. Exact match
        if expected.strip().lower() == actual.strip().lower():
            return 1.0

        # 4. Token-overlap Jaccard
        overlap = TaskScorer._token_overlap(expected, actual)
        return overlap

    @staticmethod
    def _extract_answer(session: Session) -> Optional[str]:
        """Return the last assistant message text from session events, or None."""
        for event in reversed(session.events):
            role = getattr(event, "role", None)
            message = getattr(event, "message", None)
            if role == "assistant" and message:
                return str(message)
        return None

    @staticmethod
    def _token_overlap(a: str, b: str) -> float:
        """Token-level Jaccard similarity — no external dependencies."""
        tokens_a = set(a.lower().split())
        tokens_b = set(b.lower().split())
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        return intersection / union
