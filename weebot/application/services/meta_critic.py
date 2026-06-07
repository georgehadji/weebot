"""MetaCritic — post-task trajectory analysis for future improvement.

After a PlanActFlow session completes, the MetaCritic reviews the full
trajectory (plan, steps, tool calls, results) and produces structured
meta-notes that are injected into future planning cycles.  This closes
the improvement loop: every completed task feeds back into the planner.

Implements Enhancement 1 from the HyperAgents plan:
docs/plans/hyperagents-enhancement-plan.md
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.config.model_refs import MODEL_BUDGET

logger = logging.getLogger(__name__)

# Inline fallback kept in sync with the structured prompt below.
_META_CRITIC_SYSTEM_PROMPT = """You are a meta-critic. Review a completed task trajectory and produce
actionable insights for future planning.  Be specific — vague advice like
"be more careful" is useless.  Point to concrete step IDs, tool choices,
and failure patterns.

Output ONLY valid JSON:
{
  "what_worked": ["concrete thing that worked"],
  "what_failed": ["concrete thing that failed"],
  "strategy_change": "one actionable change for the planner next time"
}"""

_META_CRITIC_USER_TEMPLATE = """Review this completed task trajectory:

Task: {task_description}
Plan: {plan_summary}
Steps executed: {step_count}
Tool calls made: {tool_count}
Failures: {failure_count}
Step results:
{step_results}

Produce a structured critique.  Focus on what the PLANNER should do
differently next time, not on surface-level execution issues."""


@dataclass
class MetaCritiqueResult:
    """Structured output from a meta-critique."""

    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    strategy_change: str = ""
    raw_json: dict[str, Any] = field(default_factory=dict)

    @property
    def meta_note(self) -> str:
        """Single-line summary suitable for session.meta_notes."""
        parts: list[str] = []
        if self.strategy_change:
            parts.append(f"Strategy: {self.strategy_change}")
        if self.what_failed:
            parts.append(f"Avoid: {'; '.join(self.what_failed[:2])}")
        return " | ".join(parts) if parts else "No actionable insights"

    @classmethod
    def empty(cls) -> "MetaCritiqueResult":
        return cls(
            what_worked=[],
            what_failed=[],
            strategy_change="",
        )


class MetaCritic:
    """Post-task trajectory analyst.

    Uses a budget-tier LLM to keep costs near zero.  If the LLM call fails
    or returns unparseable output, an empty result is returned — meta-analysis
    must never block task completion.
    """

    _CHARS_PER_STEP_RESULT: int = 200
    _MAX_STEP_RESULTS: int = 8

    def __init__(self, llm: LLMPort):
        self._llm = llm

    async def critique(
        self,
        task_description: str,
        plan_summary: str,
        step_results: list[tuple[str, str]],  # (step_id, result_summary)
        failures: list[str],
        tool_count: int = 0,
    ) -> MetaCritiqueResult:
        """Analyze a completed trajectory and return actionable insights.

        Args:
            task_description: The original user task.
            plan_summary: Summary of the plan (title + message).
            step_results: List of (step_id, result_summary) tuples.
            failures: List of failure/error messages.
            tool_count: Total tool calls across all steps.

        Returns:
            MetaCritiqueResult with what_worked, what_failed, strategy_change.
        """
        # Truncate step results to keep the prompt small
        truncated_steps: list[str] = []
        for step_id, result in step_results[-self._MAX_STEP_RESULTS:]:
            short = result[:self._CHARS_PER_STEP_RESULT]
            truncated_steps.append(f"  {step_id}: {short}")

        user_prompt = _META_CRITIC_USER_TEMPLATE.format(
            task_description=task_description,
            plan_summary=plan_summary,
            step_count=len(step_results),
            tool_count=tool_count,
            failure_count=len(failures),
            step_results="\n".join(truncated_steps) or "(no step results)",
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _META_CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            resp: LLMResponse = await self._llm.chat(
                messages=messages,
                model=MODEL_BUDGET,
                temperature=TEMPERATURE_DEFAULT,
                max_tokens=MAX_TOKENS_SHORT,
            )
            parsed = self._parse_response(resp.content or "")
            if parsed:
                return parsed
        except Exception as exc:
            logger.warning("MetaCritic LLM call failed: %s", exc)

        return MetaCritiqueResult.empty()

    @staticmethod
    def _parse_response(content: str) -> MetaCritiqueResult | None:
        """Parse the LLM's JSON response into a MetaCritiqueResult."""
        try:
            # Strip code fences if present
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)

            data = json.loads(text)
            return MetaCritiqueResult(
                what_worked=data.get("what_worked", []),
                what_failed=data.get("what_failed", []),
                strategy_change=data.get("strategy_change", ""),
                raw_json=data,
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.debug("MetaCritic parse failed: %s", exc)
            return None
