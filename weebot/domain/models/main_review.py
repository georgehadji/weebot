"""MainReview — risk assessment for a gate-approved idea contract."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MainVerdict(str, Enum):
    APPROVED_FOR_CODER = "approved_for_coder"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class RiskBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MainReview(BaseModel):
    """Result of risk-scoring an idea contract that passed IntentReview."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    idea_contract_id: str = Field(default="")
    intent_review_id: str = Field(default="")
    verdict: MainVerdict = Field(default=MainVerdict.DEFERRED)
    risk_band: RiskBand = Field(default=RiskBand.MEDIUM)
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    rationale: str = Field(default="")
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
