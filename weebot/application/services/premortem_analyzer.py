"""PremortmAnalyzer — prospective failure analysis before plan execution.

Implements the Gary Klein pre-mortem methodology: ask the LLM to imagine
the plan has already failed and surface likely failure causes.  The output
is a list of risk strings injected into the plan as notes.

Design notes:
- Uses budget-tier model (cheap, fast, non-critical path).
- On timeout or parse failure, returns an empty list (non-blocking).
- 3 risks max — enough signal without bloating the plan.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weebot.application.ports.llm_port import LLMPort
    from weebot.domain.models.plan import Plan

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a pre-mortem analyst. Imagine it is 3 months from now
and the plan below has completely failed. Reason backwards: what went wrong?

Focus on concrete, specific failure modes — not vague advice.

Return ONLY valid JSON (no markdown, no fences):
{"risks": ["risk 1", "risk 2", "risk 3"]}

Maximum 3 risks, each under 100 characters."""

_MAX_RISKS = 3
_TIMEOUT_SECONDS = 8.0


class PremortmAnalyzer:
    """Runs a pre-mortem analysis on a plan and returns a list of risk strings."""

    def __init__(self, llm: "LLMPort", timeout_seconds: float = _TIMEOUT_SECONDS) -> None:
        self._llm = llm
        self._timeout = timeout_seconds

    async def analyze(self, plan: "Plan", task: str) -> list[str]:
        """Return up to 3 prospective failure causes for *plan*.

        On timeout or parse failure, returns [] so the flow is never blocked.
        """
        try:
            steps_text = "\n".join(
                f"  {i+1}. {s.description}" for i, s in enumerate(plan.steps)
            )
            user_msg = (
                f"Task: {task}\n\nPlan:\n{steps_text}\n\n"
                "What are the most likely causes of failure?"
            )
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.4,
                    max_tokens=200,
                ),
                timeout=self._timeout,
            )
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(raw)
            risks = [str(r) for r in data.get("risks", []) if r]
            return risks[:_MAX_RISKS]
        except Exception as exc:
            logger.debug("PremortmAnalyzer non-blocking failure: %s", exc)
            return []
