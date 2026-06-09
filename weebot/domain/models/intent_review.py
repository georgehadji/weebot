"""IntentReview — gate review of an idea contract's coherence and safety."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class IntentVerdict(str, Enum):
    READY = "ready"           # coherent and actionable
    NOT_READY = "not_ready"   # needs clarification
    BLOCKED = "blocked"       # unsafe or out of scope


class IntentReview(BaseModel):
    """Result of reviewing an idea contract's intent."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    idea_contract_id: str = Field(default="")
    verdict: IntentVerdict = Field(default=IntentVerdict.NOT_READY)
    reasoning: str = Field(default="")
    clarification_needed: list[str] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
