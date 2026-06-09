"""IntentReviewPort — abstract interface for reviewing idea contracts."""
from __future__ import annotations

from abc import ABC, abstractmethod

from weebot.domain.models.idea_contract import IdeaContract
from weebot.domain.models.intent_review import IntentReview


class IntentReviewPort(ABC):
    """Review an idea contract's coherence, actionability, and safety.

    Fail-open: return NOT_READY on any error.
    """

    @abstractmethod
    async def review(self, contract: IdeaContract) -> IntentReview:
        ...
