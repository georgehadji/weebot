"""CodeReviewerService — LLM-backed per-step code review.

Uses MODEL_CODE_REVIEW (grok-4.3 — reasoning, 1M context) to review the
output of each code-producing step before the flow advances.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.code_reviewer_port import CodeReviewerPort
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.plan import Step

logger = logging.getLogger(__name__)

_REVIEWER_SYSTEM_PROMPT = """You are a senior code reviewer. A coding agent just completed
one step of a multi-step task. Review what it did and flag real problems only.

Check for:
1. Security issues: hardcoded secrets, unvalidated input, SQL injection, path traversal
2. Correctness bugs: off-by-one errors, wrong logic, missing edge cases, incorrect API usage
3. Missing error handling: uncaught exceptions, unhandled failure modes
4. Architectural violations: wrong layer imports, mutating shared state, circular deps
5. Scope creep: the step did something outside its description

Do NOT flag:
- Style preferences, minor naming choices, or improvements unrelated to correctness
- Hypothetical future issues
- Things that are handled in other steps

Respond with a single JSON object (no markdown, no fences):
{
  "verdict":    "approved" | "revise" | "reject",
  "issues":     ["specific finding 1", ...],
  "hint":       "one actionable instruction for the agent if verdict is revise",
  "confidence": 0.0-1.0,
  "severity":   "info" | "warning" | "error"
}

Use "reject" only for unrecoverable issues (security breach, data loss risk).
Use "revise" for fixable correctness/error-handling problems.
Use "approved" when the step is good enough to proceed."""

_MAX_TOKENS = 512
_TEMPERATURE = 0.1


class CodeReviewerService(CodeReviewerPort):
    """LLM-backed code reviewer. Fail-open: returns approved on any failure."""

    def __init__(
        self,
        llm: LLMPort,
        timeout_seconds: float = 8.0,
    ) -> None:
        """
        Args:
            llm: LLMPort instance. Should target MODEL_CODE_REVIEW (grok-4.3).
            timeout_seconds: Max wait for the LLM call. Returns approved on timeout.
        """
        self._llm = llm
        self._timeout_seconds = timeout_seconds

    async def review(self, step: Step, context: dict[str, Any]) -> CodeReviewResult:
        """Review a completed step's output. Never raises — returns approved on failure."""
        try:
            prompt = self._build_prompt(step, context)
            response = await asyncio.wait_for(
                self._llm.chat(
                    messages=[
                        {"role": "system", "content": _REVIEWER_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=_MAX_TOKENS,
                    temperature=_TEMPERATURE,
                ),
                timeout=self._timeout_seconds,
            )

            raw = (response.content or "").strip()
            # Strip markdown fences — handles both multi-line and one-liner forms
            import re
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            data = json.loads(raw)
            # Clamp confidence to [0.0, 1.0] before constructing the model
            conf = min(1.0, max(0.0, float(data.get("confidence", 1.0))))
            result = CodeReviewResult(
                step_id=step.id,
                verdict=data.get("verdict", "approved"),
                issues=data.get("issues", []),
                hint=data.get("hint", ""),
                confidence=conf,
                severity=data.get("severity", "info"),
            )
            logger.info(
                "Code review step=%s verdict=%s confidence=%.2f issues=%d",
                step.id, result.verdict, result.confidence, len(result.issues),
            )
            return result

        except Exception as exc:
            logger.warning(
                "Code reviewer failed for step %s (%s). Proceeding as approved.",
                step.id, exc,
            )
            return CodeReviewResult(step_id=step.id, verdict="approved")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, step: Step, context: dict[str, Any]) -> str:
        task = context.get("task", "unknown task")
        plan_title = context.get("plan_title", "")
        n_complete = context.get("completed_steps", 0)
        step_events = context.get("step_events", [])

        tool_lines = self._render_tool_events(step_events, max_events=10)

        result_section = (
            f"Result reported: {step.result}"
            if step.result
            else "Result reported: (none)"
        )

        return (
            f"## Task\n{task}\n\n"
            f"## Plan\n{plan_title}  (step {n_complete + 1})\n\n"
            f"## Step Description\n{step.description}\n\n"
            f"## {result_section}\n\n"
            f"## Tool Calls Made\n{tool_lines or '(no tool call events recorded)'}"
        )

    @staticmethod
    def _render_tool_events(events: list[Any], max_events: int) -> str:
        """Extract tool-call summaries from raw serialised event dicts."""
        lines = []
        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get("type") == "tool":
                tool_name = e.get("tool_name", "?")
                tool_input = str(e.get("tool_input", ""))[:200]
                lines.append(f"- {tool_name}({tool_input})")
            if len(lines) >= max_events:
                break
        return "\n".join(lines)
