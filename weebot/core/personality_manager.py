"""PersonalityManager — loads WEEBOT_CORE.md and injects it into agent context.

Provides a centralized identity and instruction system.  The global
WEEBOT_CORE.md defines invariant rules, base behaviors, and the agent's
core persona across all roles and profiles.

The core file uses XML-scoped tags (<identity>, <invariant_rules>, etc.)
for deterministic section extraction.  Tags are stripped before injection
— the LLM sees clean markdown.

Maps to Hermes Evolution Phase 1.1 (Enhancement 1 — XML-scoped prompts).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from weebot.domain.models.personality import RoleSectionMapping

logger = logging.getLogger(__name__)

# Default location: project root (alongside WEEBOT_CORE.md)
_CORE_FILE = Path(__file__).resolve().parent.parent.parent / "WEEBOT_CORE.md"


class PersonalityManager:
    """Manages the core personality and safeguard injections.

    Parses WEEBOT_CORE.md into XML-tagged sections and returns only
    the sections relevant to the active role.

    Args:
        core_path: Path to the WEEBOT_CORE.md file.
                   Defaults to project-root / WEEBOT_CORE.md.
    """

    def __init__(self, core_path: Optional[Path] = None) -> None:
        self._core_path = core_path or _CORE_FILE
        self._sections: dict[str, str] = {}  # tag_name → content (XML stripped)
        self._load()

    def _load(self) -> None:
        """Read and parse the core personality file into sections."""
        if not self._core_path.exists():
            logger.warning("Core personality file not found: %s", self._core_path)
            self._sections = {}
            return
        try:
            raw = self._core_path.read_text(encoding="utf-8")
            self._sections = self._parse_xml_sections(raw)
            logger.info(
                "Loaded core personality: %s (%d sections, %d chars)",
                self._core_path, len(self._sections), len(raw),
            )
        except Exception as exc:
            logger.warning("Failed to read core personality: %s", exc)
            self._sections = {}

    @staticmethod
    def _parse_xml_sections(raw: str) -> dict[str, str]:
        """Parse XML-tagged sections from *raw* content.

        Extracts content between <tagname> and </tagname> markers,
        stripping the tags themselves.  Preserves the inner markdown
        content exactly.

        Returns:
            dict mapping tag name → markdown content (tags stripped).
        """
        sections: dict[str, str] = {}
        pattern = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)
        for match in pattern.finditer(raw):
            tag = match.group(1)
            content = match.group(2).strip()
            if content:
                sections[tag] = content
        return sections

    def get_system_prompt(self, role: Optional[str] = None) -> str:
        """Return the core personality block for system prompt injection.

        Args:
            role: Optional role name.  Only sections mapped to this role
                  via RoleSectionMapping will be included.

        Returns:
            Markdown-formatted core instruction block, or empty string.
        """
        if not self._sections:
            return ""

        # Determine which sections to include
        if role:
            section_tags = RoleSectionMapping.sections_for_role(role)
        else:
            section_tags = list(self._sections.keys())

        # Build the prompt from selected sections
        parts: list[str] = ["## Core Identity & Safeguards"]
        if role:
            parts[0] += f" (role: {role})"

        for tag in section_tags:
            content = self._sections.get(tag)
            if content:
                # Derive section header from tag name
                header = tag.replace("_", " ").title()
                parts.append(f"\n### {header}\n{content}")

        return "\n\n".join(parts) + "\n\n"

    def refresh(self) -> None:
        """Re-read the core file (for hot-reload)."""
        self._load()

    @property
    def loaded(self) -> bool:
        """True if at least one core personality section is available."""
        return bool(self._sections)

    @property
    def content(self) -> str:
        """Raw concatenation of all parsed sections (tags stripped)."""
        return "\n\n".join(self._sections.values())

    @property
    def section_names(self) -> list[str]:
        """Return the names of all parsed sections."""
        return list(self._sections.keys())
