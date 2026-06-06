"""Trajectory domain models — scored execution records + degenerate pattern detection.

TrajectorySummary / OptimizationBatch are the input to the SkillOpt optimizer.
TrajectoryHealth / TrajectoryDiagnosis are used by the TrajectoryMonitor (Tier 1.3)
for real-time degenerate pattern detection during execution.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TrajectorySummary(BaseModel):
    """Compact representation of a single task execution for the optimizer."""

    task_id: str = Field(description="Unique task identifier")
    session_id: str = Field(description="Session that produced this trajectory")
    skill_name: str = Field(default="", description="Name of the skill used")
    skill_version: int = Field(default=0, description="Skill version at execution time")
    harness: str = Field(
        default="direct_chat",
        description='Execution harness: "direct_chat" | "codex" | "claude_code"',
    )
    score: float = Field(ge=0.0, le=1.0, description="Benchmark-native score (0.0 – 1.0)")
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

    def add(self, t: TrajectorySummary) -> "OptimizationBatch":
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


class TrajectoryHealth(str, Enum):
    """Health classification of a trajectory after a step (Tier 1.3)."""

    HEALTHY = "healthy"
    REPEATING = "repeating"          # Same tool call 4+ consecutive times
    SEMANTIC_LOOP = "semantic_loop"  # Different calls, identical output
    STAGNATING = "stagnating"        # No progress across multiple steps
    BUDGET_HOTSPOT = "budget_hotspot"  # One sub-goal consuming >40% budget
    EXHAUSTED = "exhausted"          # Budget at 90%+ with no completion
    TERMINAL = "terminal"            # All tool calls failing — stop immediately


class TrajectoryDiagnosis(BaseModel):
    """Result of diagnosing the current trajectory health (Tier 1.3)."""

    health: TrajectoryHealth = Field(default=TrajectoryHealth.HEALTHY)
    detail: str = Field(default="")
    recovery_message: str = Field(
        default="",
        description="Injected into the executor's conversation buffer",
    )
    affected_step_ids: list[str] = Field(default_factory=list)
