"""SkillVariant — archived stepping stone for open-ended skill improvement.

Implements Enhancement 4 from the HyperAgents plan: each skill variant
generated during SkillOptFlow is persisted in an archive with lineage
tracking.  Parent selection uses a novelty bonus to prevent premature
convergence.

See: docs/plans/hyperagents-enhancement-plan.md
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class SkillVariant(BaseModel):
    """A single skill variant in the improvement archive.

    Each variant tracks its parent (for lineage), evaluation score,
    domain, and generation depth.  The children_count is maintained
    externally by the store and used for novelty-biased selection.
    """

    variant_id: str = Field(default="")
    parent_id: Optional[str] = Field(default=None)
    skill_name: str = Field(default="")
    skill_content: str = Field(default="")
    content_hash: str = Field(default="")  # SHA-256 for dedup
    score: float = Field(default=0.0)
    domain: str = Field(default="")
    generation: int = Field(default=0)  # depth in family tree
    children_count: int = Field(default=0)
    meta_notes: str = Field(default="")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
