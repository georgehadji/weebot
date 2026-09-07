"""SessionStamp — machine-readable metadata emitted at session completion.

Inspired by Hallmark's stamp pattern: every output carries a machine-readable
block so future runs can make diversification and audit decisions without
re-reading the full session history.
"""

from __future__ import annotations


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
        default="", description="SHA-256 hash (8 chars) of the plan's structural fingerprint."
    )
    verification: VerificationScores | None = Field(default=None)
    gate_failures: list[str] = Field(default_factory=list)
    verification_status: str = Field(
        default="",
        description=(
            "Whether verification actually RAN: '', 'passed', 'failed' or 'not_run'. "
            "`verifying.py` has always computed this and written it to "
            "`context.extra['verification_status']`, and nothing read it — this model "
            "forbids extra keys and had no field for it, so the NOT_RUN marker could "
            "not reach the stamp even if a consumer had wanted it. An empty "
            "`gate_failures` list means 'no gate failed', which is what a gate that "
            "could not run also produces."
        ),
    )
    tool_calls: int = Field(default=0)
    errors: int = Field(default=0)
    duration_ms: int = Field(default=0)
    completed_at: str = Field(default="", description="ISO-8601 timestamp of session completion.")

    model_config = {"extra": "forbid"}
