"""RetentionReview — keep/improve/park/prune recommendation.

Domain models for Enhancement 5: whether a completed session should be
retained as reference, improved, archived, or recommended for deletion.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RetentionVerdict(str, Enum):
    KEEP = "keep"         # durable value, keep as reference
    IMPROVE = "improve"   # value exists but quality gaps — surface to user
    PARK = "park"         # completed, low reuse — archive
    PRUNE = "prune"       # failed/stale — recommend deletion (never triggers deletion)


class RetentionReview(BaseModel):
    """Recommendation for what to do with a completed session."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default="")
    verdict: RetentionVerdict = Field(default=RetentionVerdict.PARK)
    reasoning: str = Field(default="")
    improvement_notes: list[str] = Field(default_factory=list)
    trust_band_at_review: Optional[str] = Field(default=None)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
