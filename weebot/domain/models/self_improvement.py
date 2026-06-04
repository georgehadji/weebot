"""Controlled self-improvement domain model — patches to skill/config files.

Patches are validated through AST parsing + sandbox execution before apply.
Only skills, contracts, rules, and harness configs are editable.
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
