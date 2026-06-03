"""SkillSource models — source format detection for skill conversion (Enhancement 10).

Unified converter handles 5 formats: Weebot (native), Manus (SKILL.md + YAML
frontmatter), OpenClaw (same as Manus), MyManus (plugin.json), AgenticSeek
(.txt with XML tags).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SourceFormat(str, Enum):
    """Detected source skill format."""
    WEEBOT = "weebot"             # Native: manifest.json + prompt.md
    MANUS = "manus"               # SKILL.md with YAML frontmatter
    OPENCLAW = "openclaw"         # Same as MANUS
    MYMANUS = "mymanus"           # plugin.json + SKILL.md
    AGENTICSEEK = "agenticseek"   # .txt with <agent_loop> or <system_capability> tags
    UNKNOWN = "unknown"           # Cannot determine format


class SkillSource(BaseModel):
    """A skill detected at a given path with its source format."""

    path: str = Field(default="", description="Absolute path to the skill directory or file")
    format: SourceFormat = Field(default=SourceFormat.UNKNOWN)
    name: str = Field(default="", description="Derived skill name (may differ from source)")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
