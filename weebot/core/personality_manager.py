"""PersonalityManager — loads WEEBOT_CORE.md and SOUL.md, injects into agent context.

Provides a centralized identity and instruction system.  Supports two
identity sources, assembled in Hermes-compatible order:

1. **SOUL.md** (slot #1) — free-form markdown persona.  Injected verbatim
   as the agent's core identity.  Per-profile via ``~/.weebot/profiles/<name>/SOUL.md``
   or project-root ``./SOUL.md``.  Hot-reloaded every turn.

2. **WEEBOT_CORE.md** (slot #2) — XML-scoped invariant rules and safeguards.
   Sections are filtered by role via ``RoleSectionMapping``.  Tags are stripped
   before injection — the LLM sees clean markdown.

Maps to Hermes Evolution Phase 1.1 (Enhancement 1 — XML-scoped prompts)
and SOUL.md support (Enhancement 11).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from weebot.domain.models.personality import RoleSectionMapping

if TYPE_CHECKING:
    from weebot.application.ports.soul_provider_port import SoulProviderPort

logger = logging.getLogger(__name__)

# Default location: project root (alongside WEEBOT_CORE.md)
_CORE_FILE = Path(__file__).resolve().parent.parent.parent / "WEEBOT_CORE.md"


class PersonalityManager:
    """Manages the core personality and safeguard injections.

    Parses WEEBOT_CORE.md into XML-tagged sections and returns only
    the sections relevant to the active role.

    When a ``SoulProviderPort`` is injected, SOUL.md content is loaded
    and prepended to the system prompt as the agent's primary identity (slot #1).

    Args:
        core_path: Path to the WEEBOT_CORE.md file.
                   Defaults to project-root / WEEBOT_CORE.md.
        soul_provider: Optional SoulProviderPort for loading SOUL.md identities.
        profile_name: Default profile name for SOUL.md loading (can be
                      overridden per-call in ``get_system_prompt()``).
    """

    def __init__(
        self,
        core_path: Optional[Path] = None,
        soul_provider: Optional["SoulProviderPort"] = None,
        profile_name: Optional[str] = None,
    ) -> None:
        self._core_path = core_path or _CORE_FILE
        self._soul_provider = soul_provider
        self._profile_name = profile_name
        self._sections: dict[str, str] = {}  # tag_name → content (XML stripped)
        self._soul_cache: dict[str, str] = {}  # profile_name → SOUL.md content
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

    def get_system_prompt(
        self,
        role: Optional[str] = None,
        profile_name: Optional[str] = None,
    ) -> str:
        """Return the assembled system prompt: SOUL.md (slot #1) + WEEBOT_CORE.md (slot #2).

        Assembly order follows the Hermes pattern:
        1. SOUL.md content — the agent's identity/persona (free-form markdown)
        2. WEEBOT_CORE.md sections — invariant rules and safeguards (XML-tag-filtered by role)

        Args:
            role: Optional role name.  Only WEEBOT_CORE.md sections mapped to
                  this role via RoleSectionMapping will be included.
            profile_name: Override the default profile for SOUL.md loading.
                          When ``None``, uses the profile set at construction time.

        Returns:
            Markdown-formatted system prompt block, or empty string.
        """
        parts: list[str] = []

        # ── Slot 1: SOUL.md identity ────────────────────────────────
        soul = self._load_soul(profile_name)
        if soul:
            parts.append(soul)

        # ── Slot 2: WEEBOT_CORE.md safeguards ────────────────────────
        core = self._build_core_prompt(role)
        if core:
            parts.append(core)

        if not parts:
            return ""

        return "\n\n".join(parts) + "\n\n"

    def _load_soul(self, profile_name: Optional[str] = None) -> str | None:
        """Load SOUL.md content, with per-profile caching.

        Since ``SoulProviderPort.load()`` is async but ``get_system_prompt()``
        is synchronous, we bridge via ``asyncio.run()``.  This is acceptable
        because SOUL.md reads are fast local file I/O.

        Content is cached per-profile in ``_soul_cache``.  Call ``refresh()``
        to invalidate the entire cache (hot-reload).
        """
        if self._soul_provider is None:
            return None

        effective_profile = profile_name or self._profile_name or "default"
        cache_key = effective_profile

        if cache_key in self._soul_cache:
            cached = self._soul_cache[cache_key]
            return cached if cached else None

        import asyncio

        async def _load():
            try:
                profile = await self._soul_provider.load(effective_profile)
                if profile and not profile.is_empty:
                    return profile.content
            except Exception:
                logger.debug("SOUL.md load failed — using fallback", exc_info=True)
            return ""

        try:
            result = asyncio.run(_load())
        except RuntimeError:
            # Already inside an event loop — skip SOUL.md for this call
            logger.debug("Cannot load SOUL.md inside running event loop")
            return None

        self._soul_cache[cache_key] = result
        return result if result else None

    def _build_core_prompt(self, role: Optional[str] = None) -> str | None:
        """Build the WEEBOT_CORE.md section of the system prompt."""
        if not self._sections:
            return None

        if role:
            section_tags = RoleSectionMapping.sections_for_role(role)
        else:
            section_tags = list(self._sections.keys())

        parts: list[str] = ["## Core Identity & Safeguards"]
        if role:
            parts[0] += f" (role: {role})"

        for tag in section_tags:
            content = self._sections.get(tag)
            if content:
                header = tag.replace("_", " ").title()
                parts.append(f"\n### {header}\n{content}")

        return "\n\n".join(parts)

    def refresh(self) -> None:
        """Re-read both SOUL.md and WEEBOT_CORE.md (for hot-reload)."""
        self._load()
        self._soul_cache.clear()  # invalidate SOUL.md cache

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
