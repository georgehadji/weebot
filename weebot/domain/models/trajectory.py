"""Trajectory domain models — scored execution records for skill optimization.

A TrajectorySummary is the input to the SkillOpt optimizer model.  It
condenses a full session event stream into a compact (~500–2000 token)
natural-language representation of what the agent did, what score it
achieved, and what failure/success patterns were observed.

An OptimizationBatch groups trajectories from one rollout step so the
optimizer can perform minibatch reflection over failures and successes.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TrajectorySummary(BaseModel):
    """Compact representation of a single task execution for the optimizer.

    This is what the optimizer model sees — not the full event stream.
    Typical size: 500–2000 tokens per trajectory.
    """

    task_id: str = Field(description="Unique task identifier")
    session_id: str = Field(description="Session that produced this trajectory")
    skill_name: str = Field(default="", description="Name of the skill used")
    skill_version: int = Field(default=0, description="Skill version at execution time")
    harness: str = Field(
        default="direct_chat",
        description='Execution harness: "direct_chat" | "codex" | "claude_code"',
    )
    score: float = Field(
        ge=0.0, le=1.0, description="Benchmark-native score (0.0 – 1.0)"
    )
    passed: bool = Field(default=False, description="True when score meets pass threshold")
    failure_modes: list[str] = Field(
        default_factory=list,
        description="Categorised failure modes, e.g. ['wrong_tool_choice', 'format_error']",
    )
    success_patterns: list[str] = Field(
        default_factory=list,
        description="Categorised success patterns, e.g. ['verified_output', 'correct_ordering']",
    )
    tool_call_count: int = Field(default=0, description="Number of tool calls made")
    total_tokens: int = Field(default=0, description="Total tokens consumed")
    total_cost: float = Field(default=0.0, description="Total cost in USD")
    trajectory_text: str = Field(
        default="",
        description="Compact natural-language trace for the optimizer model",
    )
    answer: Optional[str] = Field(default=None, description="Final answer produced")
    expected_answer: Optional[str] = Field(
        default=None, description="Expected/gold answer for scoring"
    )


class OptimizationBatch(BaseModel):
    """A batch of trajectories for one optimizer step."""

    skill_name: str = Field(description="Name of the skill used for this batch")
    skill_version: int = Field(default=0, description="Skill version used")
    trajectories: list[TrajectorySummary] = Field(default_factory=list)
    batch_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Average score across all trajectories"
    )
    failure_count: int = Field(default=0)
    success_count: int = Field(default=0)

    def add(self, t: TrajectorySummary) -> OptimizationBatch:
        """Return a new batch with *t* appended, recomputing aggregates."""
        new_trajs = list(self.trajectories) + [t]
        total_score = sum(t.score for t in new_trajs)
        return OptimizationBatch(
            skill_name=self.skill_name,
            skill_version=self.skill_version,
            trajectories=new_trajs,
            batch_score=total_score / len(new_trajs) if new_trajs else 0.0,
            failure_count=sum(1 for t in new_trajs if not t.passed),
            success_count=sum(1 for t in new_trajs if t.passed),
        )
