"""CodeReviewerPort — abstract interface for per-step code review."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.plan import Step


class CodeReviewerPort(ABC):
    """Interface for LLM-backed per-step code review.

    Called by ReviewingState after ExecutingState marks a step COMPLETED
    and before the flow advances to the next step.

    Implementations must be fail-open: a timeout or parse error must return
    a default CodeReviewResult(verdict="approved") rather than propagating
    the exception into the flow.
    """

    @abstractmethod
    async def review(self, step: Step, context: dict[str, Any]) -> CodeReviewResult:
        """Review the output of a completed step.

        Args:
            step: The just-completed step. Fields of interest:
                  - step.description: what the executor was asked to do
                  - step.result:      what the executor reported doing
                  - step.id:          for the CodeReviewResult.step_id
            context: Execution context dict. Keys provided by ReviewingState:
                  - "task":         original user task prompt
                  - "step_events":  list of serialised AgentEvent dicts from
                                    this step's execution (tool calls, output)
                  - "completed_steps": int, how many steps have run so far
                  - "plan_title":   str, the plan title for context

        Returns:
            CodeReviewResult with verdict, issues, hint, and confidence.
            Must never raise — return approved default on any failure.
        """
        ...
