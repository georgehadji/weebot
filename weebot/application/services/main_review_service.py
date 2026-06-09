"""MainReviewService — LLM-backed risk scoring for idea contracts.

Uses the "verifier" role model. Fail-open: returns DEFERRED on any error.
"""
from __future__ import annotations

import asyncio
import json
import logging

from weebot.application.ports.main_review_port import MainReviewPort
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.idea_contract import IdeaContract
from weebot.domain.models.intent_review import IntentReview
from weebot.domain.models.main_review import MainReview, MainVerdict, RiskBand

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a risk assessor. An idea has been reviewed for intent
and approved as coherent. Now assess execution risk:

1. RESOURCE USAGE — how many tool calls, API costs, or user interruptions?
2. SCOPE — is it well-bounded or likely to expand?
3. REVERSIBILITY — can changes be undone?

Return ONLY valid JSON:
{"verdict": "approved_for_coder" | "deferred" | "rejected",
 "risk_band": "low" | "medium" | "high",
 "risk_score": 0.0-1.0,
 "risk_factors": ["..."],
 "rationale": "..."}"""

_TIMEOUT = 8.0
_MAX_TOKENS = 400


class MainReviewService(MainReviewPort):
    """LLM-backed risk assessor. Fail-open: returns DEFERRED."""

    def __init__(self, llm: LLMPort, timeout: float = _TIMEOUT) -> None:
        self._llm = llm
        self._timeout = timeout

    async def review(self, contract: IdeaContract, intent: IntentReview) -> MainReview:
        try:
            # Cap intent reasoning to prevent token overflow
            _reasoning = intent.reasoning[:500]

            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"Title: {contract.title}\n\n"
                            f"Prompt: {contract.prompt[:500]}\n\n"
                            f"Intent review: {_reasoning}\n"
                            f"Estimated effort: {contract.estimated_effort}\n"
                            f"Heat score: {contract.heat_score:.2f}"
                        )},
                    ],
                    temperature=0.1,
                    max_tokens=_MAX_TOKENS,
                ),
                timeout=self._timeout,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)
            return MainReview(
                idea_contract_id=contract.id,
                intent_review_id=intent.id,
                verdict=MainVerdict(data.get("verdict", "deferred")),
                risk_band=RiskBand(data.get("risk_band", "medium")),
                risk_score=min(1.0, max(0.0, float(data.get("risk_score", 0.5)))),
                risk_factors=data.get("risk_factors", []),
                rationale=data.get("rationale", ""),
            )
        except Exception as exc:
            logger.warning("MainReview failed for %s: %s", contract.id, exc)
            return MainReview(idea_contract_id=contract.id, verdict=MainVerdict.DEFERRED)
