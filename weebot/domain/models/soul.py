"""SoulProfile — domain model for SOUL.md agent identity files.

A SoulProfile represents the free-form persona content loaded from a
SOUL.md file (Hermes-style identity).  It is injected as slot #1 of the
agent's system prompt, before WEEBOT_CORE.md safeguards.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class SoulProfile(BaseModel):
    """Free-form agent identity loaded from a SOUL.md file.

    Unlike WEEBOT_CORE.md (which uses XML-scoped tags for role-filtered
    sections), SOUL.md is plain markdown injected verbatim as the agent's
    core persona.  It occupies slot #1 of the system prompt.

    Attributes:
        name: Profile name (directory name under ~/.weebot/profiles/, or
              \"default\" for the project-root SOUL.md).
        content: Raw markdown content of the SOUL.md file.
        source_path: Absolute path to the SOUL.md file that was loaded.
        loaded_at: UTC timestamp of when the file was last read.
    """

    name: str = Field(default="default", min_length=1)
    content: str = Field(default="")
    source_path: Optional[str] = Field(default=None)
    loaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_empty(self) -> bool:
        """True when the SOUL.md file is empty or contains only comments."""
        stripped = self.content.strip()
        if not stripped:
            return True
        # Treat HTML-comment-only files as empty (template placeholder)
        lines = stripped.splitlines()
        non_comment = [l for l in lines if not l.strip().startswith("<!--")]
        return len(non_comment) == 0

    @property
    def char_count(self) -> int:
        """Number of characters in the content (for token-budget checks)."""
        return len(self.content)

    model_config = {"extra": "forbid"}
