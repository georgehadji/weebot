"""AnswerScorer — score against the gold answer when there is one.

Live sessions have no expected answer, so they keep the plan-outcome score. A
benchmark sample does, and goes to the scorer WEEBOT_SCORING_MODE names.
"""

from __future__ import annotations

from weebot.application.ports.scoring_port import ScoringPort
from weebot.domain.models.event import TrajectoryScored
from weebot.domain.models.session import Session


class AnswerScorer(ScoringPort):
    """Route a session to *answer_scorer* when an expected answer is given, else *fallback*."""

    def __init__(self, answer_scorer: ScoringPort, fallback: ScoringPort) -> None:
        self._answer_scorer = answer_scorer
        self._fallback = fallback

    async def score(self, session: Session, expected_answer: str | None = None) -> TrajectoryScored:
        if expected_answer:
            return await self._answer_scorer.score(session, expected_answer=expected_answer)
        return await self._fallback.score(session)
