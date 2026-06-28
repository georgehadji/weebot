"""RoleSectionMapping — maps agent roles to WEEBOT_CORE.md XML sections.

Each role specifies which XML tags from WEEBOT_CORE.md should be
extracted and injected into the agent's system prompt.  This enables
role-based trimming of the core identity file — a researcher agent
gets only the identity, invariant rules, and operating principles,
while an admin agent gets the full file including response style.

Maps to Hermes Evolution Phase 1.1 (Enhancement 1 — XML-scoped prompts).
"""
from __future__ import annotations

from typing import ClassVar


class RoleSectionMapping:
    """Maps agent roles to the WEEBOT_CORE.md XML sections they should receive.

    Each role specifies which XML tags to extract and inject.
    Unmapped roles fall back to all sections.
    """

    DEFAULT: ClassVar[dict[str, list[str]]] = {
        "admin": [
            "identity",
            "invariant_rules",
            "operating_principles",
            "response_style",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ],
        "researcher": [
            "identity",
            "invariant_rules",
            "operating_principles",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ],
        "analyst": [
            "identity",
            "invariant_rules",
            "operating_principles",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ],
        "automation": [
            "identity",
            "invariant_rules",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ],
        "documentation": [
            "identity",
            "operating_principles",
            "response_style",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ],
        "custom": [],  # Custom roles have no defaults
    }

    @classmethod
    def sections_for_role(cls, role: str) -> list[str]:
        """Return the list of XML tag names to include for *role*.

        Falls back to all known sections for unmapped roles.
        """
        if role in cls.DEFAULT:
            return cls.DEFAULT[role]
        # Unknown role gets everything + new sections
        return [
            "identity",
            "invariant_rules",
            "operating_principles",
            "response_style",
            "web_3d_motion",
            "youtube_downloads",
            "vision_osworld",
        ]

    @classmethod
    def all_section_tags(cls) -> list[str]:
        """Return all known section tags from the default mappings."""
        seen: set[str] = set()
        for sections in cls.DEFAULT.values():
            seen.update(sections)
        return sorted(seen)
