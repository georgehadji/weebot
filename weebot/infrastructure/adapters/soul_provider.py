"""FileSystemSoulProvider — loads SOUL.md files from disk.

Implements :class:`~weebot.application.ports.soul_provider_port.SoulProviderPort`
by reading SOUL.md from the filesystem.  Scan order:

1. ``~/.weebot/profiles/<name>/SOUL.md`` (per-profile)
2. ``./SOUL.md`` (project root)
3. ``None`` — fallback; caller uses WEEBOT_CORE.md identity section
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from weebot.application.ports.soul_provider_port import SoulProviderPort
from weebot.domain.models.soul import SoulProfile

_log = logging.getLogger(__name__)

# Default template for auto-seeding
_DEFAULT_SOUL_TEMPLATE = (
    "# Agent Persona\n"
    "\n"
    "<!--\n"
    "Edit this file to customize how weebot communicates with you.\n"
    "This content is injected as the agent's core identity.\n"
    "Changes take effect immediately — no restart needed.\n"
    "-->\n"
    "\n"
    "You are weebot, a capable AI assistant. You are helpful, direct, and\n"
    "efficient. You communicate clearly and prioritize being genuinely useful\n"
    "over being verbose. Be targeted and efficient in your work.\n"
)

# ── Prompt injection patterns (subset of bash_guard credential patterns) ──
_INJECTION_PATTERNS = [
    (
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above|foregoing)\s+(instructions?|directives?|rules?|prompts?)",
            re.IGNORECASE,
        ),
        "instruction-override",
    ),
    (
        re.compile(
            r"(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(DAN|jailbreak|evil|malicious|unethical)",
            re.IGNORECASE,
        ),
        "jailbreak-persona",
    ),
    (
        re.compile(
            r"from\s+now\s+on\s+(you\s+are|your\s+name\s+is|respond\s+as)",
            re.IGNORECASE,
        ),
        "identity-hijack",
    ),
]


class FileSystemSoulProvider(SoulProviderPort):
    """Loads SOUL.md identity files from the filesystem.

    Args:
        project_root: Project directory (searched for ./SOUL.md).
                      Defaults to current working directory.
        profiles_dir: Directory containing per-profile subdirectories.
                      Defaults to ``~/.weebot/profiles/``.
        auto_seed: When True (default), create a template SOUL.md if none exists.
        scan_for_injection: When True (default), block known prompt injection patterns.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        profiles_dir: Optional[Path] = None,
        auto_seed: bool = True,
        scan_for_injection: bool = True,
    ) -> None:
        self._project_root = project_root or Path.cwd()
        self._profiles_dir = profiles_dir or Path.home() / ".weebot" / "profiles"
        self._auto_seed = auto_seed
        self._scan_for_injection = scan_for_injection

    # ── SoulProviderPort implementation ─────────────────────────────

    async def load(self, profile_name: str | None = None) -> SoulProfile | None:
        """Load SOUL.md, trying profile-specific first, then project root.

        Returns ``None`` if no file exists and auto_seed is False.
        """
        # 1. Try per-profile
        if profile_name:
            path = self._profiles_dir / profile_name / "SOUL.md"
            if path.exists():
                return self._read_soul(profile_name, path)

        # 2. Try project root
        path = self._project_root / "SOUL.md"
        if path.exists():
            return self._read_soul("default", path)

        # 3. Auto-seed
        if self._auto_seed:
            target = (
                self._profiles_dir / profile_name / "SOUL.md"
                if profile_name
                else self._project_root / "SOUL.md"
            )
            return self._seed_file("default" if profile_name is None else profile_name, target)

        return None

    async def list_profiles(self) -> list[str]:
        """Return profile names that have SOUL.md files."""
        profiles: list[str] = []

        # Project root SOUL.md
        if (self._project_root / "SOUL.md").exists():
            profiles.append("default")

        # Profile directories
        if self._profiles_dir.exists():
            for child in sorted(self._profiles_dir.iterdir()):
                if child.is_dir() and (child / "SOUL.md").exists():
                    profiles.append(child.name)

        return profiles

    async def seed(self, profile_name: str | None = None) -> SoulProfile:
        """Create a SOUL.md from the default template.

        Raises FileExistsError if a file already exists.
        """
        name = profile_name or "default"

        if profile_name:
            target = self._profiles_dir / profile_name / "SOUL.md"
        else:
            target = self._project_root / "SOUL.md"

        if target.exists():
            raise FileExistsError(f"SOUL.md already exists at {target}")

        return self._seed_file(name, target)

    # ── Internal ─────────────────────────────────────────────────────

    def _read_soul(self, name: str, path: Path) -> SoulProfile:
        """Read and optionally scan a SOUL.md file."""
        content = path.read_text(encoding="utf-8")

        if self._scan_for_injection:
            content = self._scan_content(content, str(path))

        _log.info("Loaded SOUL.md for profile '%s' from %s", name, path)
        return SoulProfile(
            name=name,
            content=content,
            source_path=str(path.resolve()),
        )

    def _seed_file(self, name: str, path: Path) -> SoulProfile:
        """Create a SOUL.md from the template and return it."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_SOUL_TEMPLATE, encoding="utf-8")
        _log.info("Seeded default SOUL.md at %s", path)
        return SoulProfile(
            name=name,
            content=_DEFAULT_SOUL_TEMPLATE,
            source_path=str(path.resolve()),
        )

    @staticmethod
    def _scan_content(content: str, source: str) -> str:
        """Scan SOUL.md content for prompt injection patterns.

        If a pattern matches, the content is replaced with a safe fallback
        and a warning is logged.  The original file is NOT modified.
        """
        for pattern, label in _INJECTION_PATTERNS:
            if pattern.search(content):
                _log.warning(
                    "SOUL.md %s blocked: matched injection pattern '%s'",
                    source,
                    label,
                )
                return (
                    "[BLOCKED: SOUL.md contained potential prompt injection "
                    f"({label}). Using default identity instead.]\n\n"
                    "You are weebot, a capable AI assistant."
                )
        return content
