"""Self-improvement domain models — patches + cross-domain transfer strategies.

Contains:
- SelfImprovementPatch: a proposed edit to skill/config files (pre-existing)
- ImprovementStrategy: cross-domain transfer of meta-improvement knowledge
  (HyperAgents Enhancement 6)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class SelfImprovementPatch(BaseModel):
    """A proposed edit to a skill, contract, or rule file.

    Each patch goes through: propose → validate → apply (or revert).
    """
    id: str = Field(default="", description="Unique patch identifier")
    target_file: str = Field(
        default="",
        description="Relative path from weebot root (e.g. config/contracts/bash.yaml)",
    )
    target_type: str = Field(
        default="skill",
        description="'skill' | 'contract' | 'rule' | 'harness'",
    )
    diff: str = Field(default="", description="Unified diff of the change")
    validation_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Score from validation against test tasks",
    )
    validation_tasks: list[str] = Field(
        default_factory=list,
        description="Validation task descriptions that were run",
    )
    applied: bool = Field(default=False, description="Whether this patch was applied")
    reverted: bool = Field(default=False, description="Whether this patch was later reverted")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    applied_at: Optional[datetime] = Field(default=None)
    reverted_at: Optional[datetime] = Field(default=None)


# ── HyperAgents Enhancement 6 ────────────────────────────────────────────────

class ImprovementStrategy(BaseModel):
    """A meta-level improvement strategy learned from one domain.

    Strategies are domain-agnostic descriptions of how the meta-agent
    improved a skill.  They are transferred across domains when a new
    domain flow starts, providing the planner with prior experience.
    """

    strategy_id: str = Field(default="")
    source_domain: str = Field(default="")
    target_domain: Optional[str] = Field(default=None)
    meta_agent_prompt_snippet: str = Field(default="")
    effectiveness_score: float = Field(default=0.0)
    transfer_count: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def composite_score(self) -> float:
        """Composite score favoring high-effectiveness, frequently-transferred strategies.

        Formula: score × (1 + transfer_count)
        This is the inverse of the DGM-H parent selection formula because
        for strategy transfer we WANT strategies that have been validated
        across multiple domains.
        """
        return self.effectiveness_score * (1.0 + self.transfer_count)
