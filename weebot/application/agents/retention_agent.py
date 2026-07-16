"""RetentionAgent — LLM-backed session retention review.

Uses the "subagent" role (fast, lightweight). Fail-open: returns PARK.
PRUNE verdict is a recommendation only — never triggers deletion.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.retention_agent_port import RetentionAgentPort
from weebot.config.constants import MAX_TOKENS_CONCISE, TEMPERATURE_PRECISE
from weebot.domain.models.retention_review import RetentionReview, RetentionVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a session retention analyst. Review the following session
and recommend one of:

- keep:    valuable reference material, retain in long-term memory
- improve: useful but quality gaps exist — flag for user attention
- park:    routine session, low reuse value — archive
- prune:   failed or stale — recommend deletion (NEVER auto-delete)

PRUNE verdict must never trigger any deletion. It is a recommendation only.

Return ONLY valid JSON:
{"verdict": "keep" | "improve" | "park" | "prune",
 "reasoning": "...",
 "improvement_notes": ["..."]}"""

_TIMEOUT = 6.0
_MAX_TOKENS = MAX_TOKENS_CONCISE


class RetentionAgent(RetentionAgentPort):
    """LLM-backed retention reviewer. Fail-open: returns PARK."""

    def __init__(self, llm: LLMPort, timeout: float = _TIMEOUT) -> None:
        self._llm = llm
        self._timeout = timeout

    async def review(
        self,
        session_id: str,
        session_summary: str,
        trust_report: dict[str, Any] | None,
        error_count: int,
        tool_count: int,
    ) -> RetentionReview:
        try:
            trust_band = (
                trust_report.get("trust_band", "n/a")
                if trust_report else "not available"
            )
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"Session: {session_id}\n"
                            f"Summary: {session_summary[:300]}\n"
                            f"Trust band: {trust_band}\n"
                            f"Tool calls: {tool_count}\n"
                            f"Errors: {error_count}\n\n"
                            f"Recommendation:"
                        )},
                    ],
                    temperature=TEMPERATURE_PRECISE,
                    max_tokens=_MAX_TOKENS,
                ),
                timeout=self._timeout,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)
            return RetentionReview(
                session_id=session_id,
                verdict=RetentionVerdict(data.get("verdict", "park")),
                reasoning=data.get("reasoning", ""),
                improvement_notes=data.get("improvement_notes", []),
                trust_band_at_review=trust_band,
            )
        except Exception as exc:
            logger.warning("RetentionAgent failed for %s: %s", session_id, exc)
            return RetentionReview(session_id=session_id, verdict=RetentionVerdict.PARK)
