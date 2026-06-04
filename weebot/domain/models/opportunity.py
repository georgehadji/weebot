"""Opportunity domain model — autonomous proposals from the Opportunity Engine.

The engine runs as a background job every 6 hours, queries the knowledge
graph for gaps and FTS5 for recurring patterns, and surfaces the top
candidates to the user on next session start.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class OpportunityProposal(BaseModel):
    """A proposed task discovered autonomously by the Opportunity Engine.

    Stored in a ``pending_opportunities`` table and surfaced to the user
    on next interactive session start.
    """
    id: str = Field(default="", description="Unique proposal identifier")
    prompt: str = Field(
        default="",
        description="The task prompt, e.g. 'Research competitor X's new pricing model'",
    )
    source: str = Field(
        default="knowledge_gap",
        description="'knowledge_gap' | 'recurring_pattern' | 'user_interest'",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Citations from KG nodes or FTS5 search results",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Ranking score: novelty × confidence × user-interest-alignment",
    )
    estimated_effort: str = Field(
        default="medium",
        description="'low' | 'medium' | 'high' — estimated time to complete",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    presented: bool = Field(
        default=False,
        description="Whether this proposal has been shown to the user",
    )
    accepted: bool = Field(
        default=False,
        description="Whether the user accepted this proposal",
    )
