"""IdeaGate — orchestrates the dreamer→intent→main review chain.

Pure orchestrator: no LLM calls.  Chains IntentReviewPort and MainReviewPort
for each contract, returning only those approved_for_coder with verdicts set.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.intent_review_port import IntentReviewPort
from weebot.application.ports.main_review_port import MainReviewPort
from weebot.domain.models.idea_contract import IdeaContract
from weebot.domain.models.intent_review import IntentVerdict
from weebot.domain.models.main_review import MainVerdict

logger = logging.getLogger(__name__)


class IdeaGate:
    """Runs each IdeaContract through IntentReview → MainReview.

    Only contracts with MainVerdict.APPROVED_FOR_CODER are returned.
    """

    def __init__(
        self,
        intent_reviewer: IntentReviewPort,
        main_reviewer: MainReviewPort,
    ) -> None:
        self._intent_reviewer = intent_reviewer
        self._main_reviewer = main_reviewer

    async def process(self, contracts: list[IdeaContract]) -> list[IdeaContract]:
        """Return only APPROVED_FOR_CODER contracts with verdicts set."""
        approved: list[IdeaContract] = []
        for contract in contracts:
            intent = await self._intent_reviewer.review(contract)
            if intent.verdict == IntentVerdict.BLOCKED:
                logger.warning("IdeaGate BLOCKED %s: %s", contract.id, intent.reasoning[:120])
                continue
            if intent.verdict == IntentVerdict.NOT_READY:
                logger.info("IdeaGate NOT_READY %s: %s", contract.id, intent.reasoning[:120])
                continue
            main = await self._main_reviewer.review(contract, intent)
            contract = contract.model_copy(update={
                "intent_verdict": intent.verdict,
                "main_verdict": main.verdict,
            })
            if main.verdict == MainVerdict.APPROVED_FOR_CODER:
                approved.append(contract)
            else:
                logger.info(
                    "IdeaGate %s for %s: %s",
                    main.verdict.value, contract.id, main.rationale[:120],
                )
        return approved
