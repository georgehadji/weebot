"""InterAgentMessage domain model — cross-agent communication during swarm execution.

Agents within a swarm can publish findings as they discover them, allowing
other agents to leverage shared knowledge before the synthesizer runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class InterAgentMessage(BaseModel):
    """A message from one swarm agent to all others."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    sender_agent_id: str = Field(default="")
    topic: str = Field(
        default="",
        description="Short topic key, e.g. 'competitor_found', 'pricing_discovered'",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
