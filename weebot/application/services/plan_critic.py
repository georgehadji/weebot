"""PlanCriticService — lightweight LLM-based plan validation.

Uses the cheapest available model (free tier preferred) to review plans
for common failure modes before they reach the executor.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.config.constants import MAX_TOKENS_SHORT, TEMPERATURE_PRECISE
from weebot.application.ports.plan_critic_port import PlanCriticPort
from weebot.domain.models.plan import Plan, PlanCritique

logger = logging.getLogger(__name__)

_CRITIC_SYSTEM_PROMPT = """You are a plan validator. Review this plan and flag:

1. Steps that use the wrong tool for the job (e.g., using bash to read a file when file_editor exists)
2. Steps with unrealistic scope (too broad for a single step)
3. Missing preconditions (a file that should exist, a URL that should be verified first)
4. Steps that could run in parallel but are unnecessarily sequenced
5. Steps whose descriptions are too vague to execute deterministically

Respond with a JSON object (no markdown, no code fences) with these fields:
- step_scores: dict mapping step_id to a 0.0–1.0 confidence score
- flaws: list of specific concern strings
- suggestions: list of concrete fix strings
- overall_confidence: float 0.0–1.0
- verdict: "approved", "revise", or "reject"

Be concise and actionable."""


class PlanCriticService(PlanCriticPort):
    """Plan critic that uses a single cheap LLM call for validation."""

    def __init__(self, llm: LLMPort, timeout_seconds: float = 5.0) -> None:
        """Initialize the critic.

        Args:
            llm: LLMPort instance (should target the cheapest available model).
            timeout_seconds: Max seconds to wait for the critic LLM call.
                             On timeout, the plan proceeds without critique.
        """
        self._llm = llm
        self._timeout_seconds = timeout_seconds

    async def critique(self, plan: Plan, context: dict[str, Any]) -> PlanCritique:
        """Critique a plan before execution.

        Args:
            plan: The plan to review.
            context: Dict with task prompt, tool names, user preferences.

        Returns:
            PlanCritique with verdict, scores, flaws, suggestions.
            On timeout or parse failure, returns a default approved critique.
        """
        try:
            prompt = self._build_critique_prompt(plan, context)
            # `self._timeout_seconds` was stored in __init__ and never used,
            # while the constructor docstring promised "Max seconds to wait for
            # the critic LLM call. On timeout, the plan proceeds without
            # critique." There was no `wait_for` anywhere in this module — a
            # documented bound that did not exist, so a hung critic held the
            # whole flow for however long the adapter allowed.
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _CRITIC_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=MAX_TOKENS_SHORT,
                    temperature=TEMPERATURE_PRECISE,
                ),
                timeout=self._timeout_seconds,
            )

            raw = response.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                raw = raw.rsplit("\n```", 1)[0]

            data = json.loads(raw)
            return PlanCritique(
                plan_id=plan.title,
                step_scores=data.get("step_scores", {}),
                flaws=data.get("flaws", []),
                suggestions=data.get("suggestions", []),
                overall_confidence=data.get("overall_confidence", 0.8),
                verdict=data.get("verdict", "approved"),
            )

        except Exception as exc:
            # FAIL OPEN — the plan proceeds, because a critic is a quality gate
            # and blocking every run on a flaky LLM call is the worse trade.
            #
            # But LOUDLY, and this is what changed. The old fallback returned
            # `overall_confidence=0.8, verdict="approved"`, and 0.8 is EXACTLY
            # `ConfidentThresholds.WARN_THRESHOLD` — so a critic outage landed
            # in the highest routing branch and logged "Plan approved with high
            # confidence". Against a genuine clean approval the only difference
            # was an empty `step_scores`, which no caller reads. The gate
            # fabricated a verdict it had never formed.
            #
            # `degraded=True` and the flaw entry make it visible to the router,
            # to the ThoughtEvent the user sees, and to anything downstream.
            logger.warning(
                "Plan critic failed (%s) — PROCEEDING WITHOUT CRITIQUE. The plan is "
                "unreviewed, not approved.",
                exc,
                exc_info=True,
            )
            return PlanCritique(
                plan_id=plan.title,
                degraded=True,
                overall_confidence=0.8,
                verdict="unreviewed",
                flaws=[f"Plan critic did not run: {type(exc).__name__}. This plan is unreviewed."],
                suggestions=[],
            )

    def _build_critique_prompt(self, plan: Plan, context: dict[str, Any]) -> str:
        """Build the critique prompt from the plan and context.

        Args:
            plan: The plan to critique.
            context: Dict containing available tools, task prompt, etc.

        Returns:
            Formatted prompt string.
        """
        tools_str = ", ".join(context.get("tools", [])) or "unknown"
        steps_lines = []
        for i, step in enumerate(plan.steps):
            steps_lines.append(f"  Step {step.id or i}: {step.description}")

        return (
            f"## Task\n{context.get('task', 'unknown')}\n\n"
            f"## Available Tools\n{tools_str}\n\n"
            f"## Plan Steps\n" + "\n".join(steps_lines)
        )
