"""TrustReport — two-source evidence comparison → clean/watch/investigate.

Domain models for Enhancement 4: VerificationDelta + TrustReport.
Pure domain: no imports from Application or Infrastructure.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DeltaVerdict(str, Enum):
    CONFIRMED = "confirmed"             # approved by code review
    DRIFT = "drift"                     # approved but CoVe found inconsistency
    REGRESSION = "regression"           # rejected/revised by code review
    MISSING_EVIDENCE = "missing_evidence"  # no code review signal for this step


class VerificationDelta(BaseModel):
    """Per-step delta between code review verdict and CoVe consistency."""
    step_id: str = Field(default="")
    code_review_verdict: Optional[str] = Field(default=None)
    delta_verdict: DeltaVerdict = Field(default=DeltaVerdict.MISSING_EVIDENCE)
    contributing_issues: list[str] = Field(default_factory=list)


class TrustBand(str, Enum):
    CLEAN = "clean"             # all confirmed or missing_evidence
    WATCH = "watch"             # drift detected (CoVe inconsistency)
    INVESTIGATE = "investigate"  # regression present (code review rejection)


class TrustReport(BaseModel):
    """Aggregate trust assessment combining code review and CoVe signals."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="")
    trust_band: TrustBand = Field(default=TrustBand.CLEAN)
    deltas: list[VerificationDelta] = Field(default_factory=list)
    cove_passed: Optional[bool] = Field(default=None)
    confirmed_count: int = Field(default=0)
    drift_count: int = Field(default=0)
    regression_count: int = Field(default=0)
    missing_count: int = Field(default=0)
    contributing_factors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
