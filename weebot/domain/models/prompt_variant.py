"""PromptVariant — versioned agent prompt for editable self-improvement.

Implements Enhancement 5 from the HyperAgents plan: agent prompts become
versioned, editable artifacts.  The SelfImprover can propose prompt edits
alongside skill and contract edits, and successful variants are stored
in the prompt variant archive.

See: docs/plans/hyperagents-enhancement-plan.md
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PromptVariantSource(str, Enum):
    HUMAN = "human"
    SELF_IMPROVER = "self_improver"
    META_CRITIC = "meta_critic"


class PromptVariant(BaseModel):
    """A versioned prompt for an agent type.

    Each variant tracks its parent (for lineage), the agent type it applies
    to, and the source of the edit.  Prompts are stored as regular text
    files under config/prompts/variants/ with UUID filenames.
    """

    variant_id: str = Field(default="")
    parent_id: Optional[str] = Field(default=None)
    agent_type: str = Field(default="")  # "executor", "planner", "meta_critic"
    prompt_content: str = Field(default="")
    source: PromptVariantSource = Field(default=PromptVariantSource.HUMAN)
    score: float = Field(default=0.0)
    is_active: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
