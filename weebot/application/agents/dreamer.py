"""DreamerAgent — active ideation from research/failure signals → IdeaContracts.

Synthesizes opportunity proposals, failed-step events, and audit violations into
actionable IdeaContract objects.  Uses the "dreamer" role model (Kimi K2.6).
Fail-open: returns [] on any error.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from weebot.application.ports.dreamer_port import DreamerPort
from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import MAX_TOKENS_MODERATE, TEMPERATURE_BALANCED
from weebot.domain.models.idea_contract import IdeaContract, IdeaSource

logger = logging.getLogger(__name__)

_DREAMER_SYSTEM_PROMPT = """You are a dreamer agent. Your job is to surface promising
ideas from raw signals — opportunity proposals, failed tool calls, audit violations.

Given a set of signals, identify patterns, recurring themes, or novel combinations
that could become actionable tasks. Produce concrete, specific ideas — not vague
suggestions.

DO NOT approve or reject ideas — only surface them. A separate review layer
gates them.

Return a JSON array (no markdown, no fences):
[
  {
    "title": "short actionable title",
    "prompt": "full task prompt for the planner",
    "source": "opportunity_proposal",
    "evidence": ["signal that inspired this"],
    "heat_score": 0.0-1.0,
    "estimated_effort": "low|medium|high"
  }
]

Maximum 5 ideas. heat_score = urgency × novelty × confidence (0.0-1.0)."""

_MAX_CONTRACTS = 5
_TIMEOUT = 15.0


class DreamerAgent(DreamerPort):
    """Synthesizes signals into IdeaContracts. Fail-open: returns []."""

    def __init__(
        self,
        llm: LLMPort,
        max_contracts: int = _MAX_CONTRACTS,
        timeout_seconds: float = _TIMEOUT,
    ) -> None:
        self._llm = llm
        self._max_contracts = max_contracts
        self._timeout = timeout_seconds

    async def dream(
        self,
        opportunity_proposals: list[Any],
        failed_step_events: list[dict],
        audit_violations: list[Any],
        session_id: str = "",
    ) -> list[IdeaContract]:
        signals = self._compile_signals(
            opportunity_proposals, failed_step_events, audit_violations,
        )
        if not signals:
            return []

        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _DREAMER_SYSTEM_PROMPT},
                        {"role": "user", "content": self._build_prompt(signals)},
                    ],
                    temperature=TEMPERATURE_BALANCED,
                    max_tokens=MAX_TOKENS_MODERATE,
                ),
                timeout=self._timeout,
            )
            return self._parse_contracts(response.content, session_id)
        except Exception as exc:
            logger.warning("DreamerAgent failed: %s", exc)
            return []

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _compile_signals(
        proposals: list[Any], failed_events: list[dict], violations: list[Any],
    ) -> list[str]:
        texts: list[str] = []
        for p in proposals:
            desc = getattr(p, "prompt", None) or getattr(p, "description", "") or str(p)
            texts.append(f"[OPPORTUNITY] {str(desc)[:200]}")
        for e in failed_events:
            texts.append(f"[FAILURE] {e.get('error', e.get('message', str(e)))[:200]}")
        for v in violations:
            texts.append(f"[VIOLATION] {str(v)[:200]}")
        return texts[:25]  # cap at 25 signals to keep prompt bounded

    def _build_prompt(self, signals: list[str]) -> str:
        signal_block = "\n".join(f"- {s}" for s in signals)
        return (
            f"I have the following signals from the system:\n\n"
            f"{signal_block}\n\n"
            f"Surface up to {self._max_contracts} distinct ideas. "
            f"Include the source type in 'source', specific evidence quotes, "
            f"and a heat_score that reflects urgency × novelty × confidence."
        )

    def _parse_contracts(self, content: str | None, session_id: str) -> list[IdeaContract]:
        if not content:
            return []
        raw = content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("ideas", data.get("contracts", []))
        contracts = []
        for item in data[:self._max_contracts]:
            try:
                contracts.append(IdeaContract(
                    title=item.get("title", "Untitled"),
                    prompt=item.get("prompt", ""),
                    source=IdeaSource(item.get("source", "opportunity_proposal")),
                    evidence=item.get("evidence", []),
                    heat_score=min(1.0, max(0.0, float(item.get("heat_score", 0.0)))),
                    estimated_effort=item.get("estimated_effort", "medium"),
                    dreamer_session_id=session_id,
                ))
            except Exception:
                continue
        contracts.sort(key=lambda c: c.heat_score, reverse=True)
        return contracts[:self._max_contracts]
