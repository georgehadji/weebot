"""CodeReviewResult — immutable result of a per-step code review."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class CodeReviewResult(BaseModel):
    """Result of an LLM code review on a single executed step.

    Mirrors PlanCritique in shape but is scoped to one step's output
    rather than an entire plan.
    """
    step_id: str = Field(default="", description="The step that was reviewed")
    verdict: Literal["approved", "revise", "reject"] = Field(
        default="approved",
        description=(
            "approved — no issues, proceed to next step; "
            "revise   — issues found, retry this step with hint injected; "
            "reject   — unrecoverable, trigger replanning"
        ),
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Specific findings: security holes, bugs, missing error handling, etc.",
    )
    hint: str = Field(
        default="",
        description="Actionable improvement instruction injected into step description on revise",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Reviewer confidence in the verdict (lower = more uncertain)",
    )
    severity: Literal["info", "warning", "error"] = Field(
        default="info",
        description="info → cosmetic; warning → quality; error → correctness/security",
    )

    @property
    def is_actionable(self) -> bool:
        """True when the verdict requires the flow to change its path."""
        return self.verdict in ("revise", "reject")

    @property
    def summary(self) -> str:
        """One-line summary for logging and ThoughtEvent body."""
        if not self.issues:
            return f"[{self.verdict.upper()}] No issues found."
        issues_str = "; ".join(self.issues[:3])
        more = f" (+{len(self.issues) - 3} more)" if len(self.issues) > 3 else ""
        return f"[{self.verdict.upper()}] {issues_str}{more}"
