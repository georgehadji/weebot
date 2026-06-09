"""IntentReviewService — LLM-backed intent review for idea contracts.

Uses the "critic" role model to assess coherence, actionability, and safety.
Fail-open: returns NOT_READY on any error.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from weebot.application.ports.intent_review_port import IntentReviewPort
from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.idea_contract import IdeaContract
from weebot.domain.models.intent_review import IntentReview, IntentVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a gate reviewer. An idea has been proposed by the
dreamer agent. Assess whether this idea is:

1. COHERENT — is the prompt specific and actionable?
2. SAFE — does it avoid destructive or out-of-scope operations?
3. READY — does it contain enough context for a planner to start?

Return ONLY valid JSON:
{"verdict": "ready" | "not_ready" | "blocked", "reasoning": "...", "clarification_needed": [...]}"""

_TIMEOUT = 5.0
_MAX_TOKENS = 300


class IntentReviewService(IntentReviewPort):
    """LLM-backed intent reviewer. Fail-open: returns NOT_READY."""

    def __init__(self, llm: LLMPort, timeout: float = _TIMEOUT) -> None:
        self._llm = llm
        self._timeout = timeout

    async def review(self, contract: IdeaContract) -> IntentReview:
        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"Title: {contract.title}\n\n"
                            f"Prompt: {contract.prompt}\n\n"
                            f"Source: {contract.source.value}\n"
                            f"Evidence: {', '.join(contract.evidence[:5])}"
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
            return IntentReview(
                idea_contract_id=contract.id,
                verdict=IntentVerdict(data.get("verdict", "not_ready")),
                reasoning=data.get("reasoning", ""),
                clarification_needed=data.get("clarification_needed", []),
            )
        except Exception as exc:
            logger.warning("IntentReview failed for %s: %s", contract.id, exc)
            return IntentReview(idea_contract_id=contract.id, verdict=IntentVerdict.NOT_READY)
