"""SessionStamp — machine-readable metadata emitted at session completion.

Inspired by Hallmark's stamp pattern: every output carries a machine-readable
block so future runs can make diversification and audit decisions without
re-reading the full session history.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class VerificationScores(BaseModel):
    """Self-critique scores from the VerifyingState (1-5 each)."""
    correctness: int = Field(default=3, ge=1, le=5)
    completeness: int = Field(default=3, ge=1, le=5)
    specificity: int = Field(default=3, ge=1, le=5)
    restraint: int = Field(default=3, ge=1, le=5)


class SessionStamp(BaseModel):
    """Machine-readable metadata emitted on session completion.

    Stored in ``session.context.stamp``.  Read by PlanHistory for
    diversification decisions and by audit tools for traceability.
    """

    weebot_version: str = Field(default="3.1.0")
    flow_type: str = Field(default="PlanActFlow")
    task_category: str = Field(default="general")
    model_used: str = Field(default="")
    plan_fingerprint: str = Field(
        default="",
        description="SHA-256 hash (8 chars) of the plan's structural fingerprint.",
    )
    verification: Optional[VerificationScores] = Field(default=None)
    gate_failures: list[str] = Field(default_factory=list)
    tool_calls: int = Field(default=0)
    errors: int = Field(default=0)
    duration_ms: int = Field(default=0)
    completed_at: str = Field(
        default="",
        description="ISO-8601 timestamp of session completion.",
    )

    model_config = {"extra": "forbid"}
