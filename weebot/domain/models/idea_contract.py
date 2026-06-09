"""IdeaContract — proposed idea from the DreamerAgent for potential execution.

Pure domain model: no imports from Application or Infrastructure.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IdeaSource(str, Enum):
    OPPORTUNITY_PROPOSAL = "opportunity_proposal"
    FAILED_STEP = "failed_step"
    AUDIT_VIOLATION = "audit_violation"
    KG_PATTERN = "kg_pattern"


class IdeaContract(BaseModel):
    """An idea surfaced by DreamerAgent, awaiting gate review before execution."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(default="")
    prompt: str = Field(default="", description="Full task prompt for PlannerAgent if accepted")
    source: IdeaSource = Field(default=IdeaSource.OPPORTUNITY_PROPOSAL)
    source_ref: str = Field(default="", description="ID of originating signal")
    evidence: list[str] = Field(default_factory=list)
    heat_score: float = Field(default=0.0, ge=0.0, le=1.0, description="urgency × novelty × confidence")
    estimated_effort: str = Field(default="medium", description="'low' | 'medium' | 'high'")
    dreamer_session_id: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    intent_verdict: Optional[str] = Field(default=None)   # set by IntentReviewService
    main_verdict: Optional[str] = Field(default=None)     # set by MainReviewService
