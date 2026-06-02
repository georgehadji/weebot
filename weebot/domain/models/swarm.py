"""Swarm domain models — goal decomposition and parallel agent orchestration.

Phase 1 — Goal-Driven Agent Swarm.  A GoalAgent decomposes a high-level
prompt into SubGoals with auto-generated roles and tool assignments.
Sub-agents execute concurrently via dispatch_parallel_tasks, and a
SynthesizerAgent clusters results into a structured SwarmResult.
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class SubGoal(BaseModel):
    """A single decomposed sub-goal produced by the GoalAgent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str = Field(
        default="",
        description="What this sub-agent should research or accomplish",
    )
    role: str = Field(
        default="",
        description="Auto-generated role name (e.g. 'pricing_analyst')",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names assigned to this sub-agent",
    )
    priority: int = Field(default=0, description="0 = highest priority")


class SwarmSpec(BaseModel):
    """Complete swarm decomposition produced by the GoalAgent.

    This is the structured output of one LLM call — the goal agent
    reads the user's prompt and emits a SwarmSpec with all the
    sub-goals, roles, and tool assignments needed.
    """

    original_prompt: str = Field(default="")
    goals: list[SubGoal] = Field(default_factory=list)
    max_concurrency: int = Field(default=4)
    synthesis_strategy: str = Field(
        default="cluster",
        description="'cluster' | 'merge' | 'vote' — how to combine results",
    )


class SwarmResult(BaseModel):
    """Aggregated result from a completed swarm execution."""

    prompt: str = Field(default="")
    sub_results: list[dict] = Field(
        default_factory=list,
        description="Per-goal summaries: [{goal_id, role, summary, artifacts}]",
    )
    clusters: list[dict] = Field(
        default_factory=list,
        description="Synthesizer clustering: [{label, members, insight}]",
    )
    synthesis: str = Field(default="", description="Final human-readable report")
    token_cost: float = Field(default=0.0)
    elapsed_seconds: float = Field(default=0.0)
