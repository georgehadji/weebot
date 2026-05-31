"""Scoring port — harness-specific scoring of agent task executions.

Each harness (direct chat, Codex, Claude Code) implements this port to
produce benchmark-native scores and failure analysis for trajectory evidence.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session


class ScoringPort(ABC):
    """Abstract interface for scoring task executions.

    The score is always normalised to 0.0–1.0 regardless of the
    underlying benchmark metric (exact-match, F1, pass@1, etc.).
    """

    @abstractmethod
    async def score(
        self,
        session: Session,
        expected_answer: Optional[str] = None,
    ) -> TrajectoryScored:
        """Score a completed session and return a TrajectoryScored event.

        Args:
            session: The completed session to score.
            expected_answer: Optional gold answer for benchmarks that
                provide it as metadata rather than inline in the task.

        Returns:
            A TrajectoryScored domain event with score, failure modes,
            and a compact trajectory summary.
        """
        ...
