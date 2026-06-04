"""Behavioral rule domain model — persistent rules extracted from user corrections.

Rules are automatically extracted from user corrections and injected into
every future executor system prompt so the agent doesn't repeat mistakes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class BehavioralRule(BaseModel):
    """A persistent behavioral rule extracted from user feedback.

    Rules are stored in a ``behavioral_rules`` table and injected into
    the executor system prompt alongside SkillRetriever results.
    """
    id: str = Field(default="", description="Unique rule identifier")
    rule_text: str = Field(
        default="",
        description="One-sentence imperative rule, e.g. 'Never use advanced_browser for simple text extraction'",
    )
    source_session_id: str = Field(default="", description="Which session produced this correction")
    source_message: str = Field(default="", description="The user's exact correction text")
    scope: str = Field(
        default="global",
        description="'global' | 'per_skill' | 'per_tool' — how broadly this rule applies",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this rule was extracted",
    )
    applied_count: int = Field(
        default=0,
        description="How many times this rule was injected into a system prompt",
    )
    last_applied_at: Optional[datetime] = Field(
        default=None,
        description="Most recent injection time",
    )
