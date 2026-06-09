"""ReviewingState — per-step LLM code review between execution and the next step.

Inserted by ExecutingState after marking a step COMPLETED, when the step
is detected as having produced code. Verdicts:
  approved → ExecutingState (advance to next step)
  revise   → ExecutingState (same step, retry_count+1, hint injected)
  reject   → UpdatingState  (mark step FAILED, trigger replanning)
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weebot.application.flows.plan_act_flow import PlanActFlow

from weebot.application.flows.states.base import AgentStatus, FlowState
from weebot.application.ports.code_reviewer_port import CodeReviewerPort
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.event import AgentEvent, ThoughtEvent
from weebot.domain.models.plan import Step, StepStatus

logger = logging.getLogger(__name__)

# Retry cap: reviewer may request at most this many revisions per step.
_MAX_REVIEW_RETRIES = 2


class ReviewingState(FlowState):
    """LLM code review gate between step completion and next-step dispatch."""

    status = AgentStatus.REVIEWING

    def __init__(
        self,
        step: Step,
        reviewer: CodeReviewerPort | None = None,
        step_events: list[Any] | None = None,
    ) -> None:
        """
        Args:
            step:        The just-completed step (status=COMPLETED at construction).
            reviewer:    CodeReviewerPort instance. If None, falls through immediately.
            step_events: Raw serialised AgentEvent dicts from this step's execution,
                         forwarded to the reviewer for tool-call context.
        """
        self._step = step
        self._reviewer = reviewer
        self._step_events: list[Any] = step_events or []

    async def execute(
        self, context: PlanActFlow, prompt: str
    ) -> AsyncGenerator[AgentEvent, None]:
        from weebot.application.flows.states.executing import ExecutingState
        from weebot.application.flows.states.updating import UpdatingState

        # ── Fast path: no reviewer configured ──────────────────────────
        if self._reviewer is None:
            logger.debug("No code reviewer configured — passing through")
            context.set_state(ExecutingState())
            return

        # ── Guard: don't review a step that has already been revised too many times ──
        if self._step.retry_count >= _MAX_REVIEW_RETRIES:
            logger.info(
                "Step %s has reached review retry cap (%d) — approving automatically",
                self._step.id, _MAX_REVIEW_RETRIES,
            )
            context.set_state(ExecutingState())
            return

        if context._plan is None:
            logger.warning("ReviewingState: no plan on context — skipping")
            context.set_state(ExecutingState())
            return

        # ── Build review context dict ────────────────────────────────
        completed_count = len(context._plan.get_completed_steps())
        review_context: dict[str, Any] = {
            "task": prompt,
            "plan_title": context._plan.title,
            "completed_steps": completed_count,
            "step_events": self._step_events,
        }

        # ── Call the reviewer ────────────────────────────────────────
        logger.info(
            "Reviewing step %s: %s",
            self._step.id, self._step.description[:80],
        )
        result: CodeReviewResult = await self._reviewer.review(
            self._step, review_context,
        )

        # ── Emit ThoughtEvent for CLI/WebSocket/logs ─────────────────
        yield ThoughtEvent(
            step_id=self._step.id,
            thought=self._format_thought(result),
            code_review_result={
                "verdict": result.verdict,
                "confidence": result.confidence,
                "severity": result.severity,
                "issues": result.issues,
            },
        )

        # ── Route based on verdict ───────────────────────────────────
        if result.verdict == "approved":
            logger.info("Review APPROVED step %s", self._step.id)
            context.set_state(ExecutingState())

        elif result.verdict == "revise":
            logger.info(
                "Review REVISE step %s — hint: %s",
                self._step.id, result.hint[:120],
            )
            revised_step = self._step.model_copy(update={
                "status": StepStatus.PENDING,
                "retry_count": self._step.retry_count + 1,
                "description": (
                    f"{self._step.description}\n"
                    f"[Code review hint: {result.hint}]"
                    if result.hint
                    else self._step.description
                ),
            })
            context._plan = context._plan.replace_step(self._step.id, revised_step)
            context.set_state(ExecutingState())

        else:  # "reject"
            logger.warning(
                "Review REJECTED step %s — %s",
                self._step.id, result.summary,
            )
            context._plan = context._plan.update_step_status(
                self._step.id,
                StepStatus.FAILED,
                result=f"[Code review rejected] {result.summary}",
            )
            context.set_state(UpdatingState())

    @staticmethod
    def _format_thought(result: CodeReviewResult) -> str:
        lines = [
            f"**Code Review** — Verdict: {result.verdict.upper()}, "
            f"Confidence: {result.confidence:.0%}, "
            f"Severity: {result.severity}",
        ]
        if result.issues:
            lines.append("\n**Issues:**")
            lines.extend(f"- {issue}" for issue in result.issues)
        if result.hint and result.verdict == "revise":
            lines.append(f"\n**Hint:** {result.hint}")
        return "\n".join(lines)
