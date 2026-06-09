"""MainReviewPort — abstract interface for risk-scoring idea contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.idea_contract import IdeaContract
from weebot.domain.models.intent_review import IntentReview
from weebot.domain.models.main_review import MainReview


class MainReviewPort(ABC):
    """Risk-score an idea contract that passed IntentReview.

    Fail-open: return DEFERRED on any error.
    """

    @abstractmethod
    async def review(self, contract: IdeaContract, intent: IntentReview) -> MainReview:
        ...
