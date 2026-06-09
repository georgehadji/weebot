"""Skill registry — discovers, loads, and manages agent skills."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from weebot.domain.models.skill import Skill


class SkillRegistry:
    """Registry for agent skills loaded from filesystem."""

    def __init__(self, search_paths: Optional[List[Path]] = None):
        self._search_paths = search_paths or self._default_paths()
        self._skills: Dict[str, Skill] = {}

    @staticmethod
    def _default_paths() -> List[Path]:
        paths = []
        # Project-local
        cwd = Path.cwd()
        if (cwd / ".weebot" / "skills").exists():
            paths.append(cwd / ".weebot" / "skills")
        # User-global
        home = Path.home()
        if (home / ".weebot" / "skills").exists():
            paths.append(home / ".weebot" / "skills")
        # Built-in
        builtin = Path(__file__).parent.parent.parent / "skills" / "builtin"
        if builtin.exists():
            paths.append(builtin)
        return paths

    def load_all(self) -> None:
        """Discover and load all skills from search paths."""
        for path in self._search_paths:
            if not path.exists():
                continue
            for skill_dir in path.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skill = self._parse_skill(skill_file)
                    if skill:
                        self._skills[skill.name] = skill

    def list_names(self) -> list[str]:
        """Return all loaded skill names."""
        return list(self._skills.keys())

    def list_all(self) -> dict[str, "Skill"]:
        """Return all loaded skills as a dict."""
        return dict(self._skills)

    def get(self, name: str) -> "Skill | None":
        """Get a skill by name, or None if not loaded."""
        return self._skills.get(name)

    @staticmethod
    def _parse_skill(filepath: Path) -> Optional[Skill]:
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception:
            return None

        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        import yaml
        frontmatter = yaml.safe_load(parts[1])
        content = parts[2].strip()

        meta = frontmatter.get("metadata", {})
        openclaw_meta = meta.get("openclaw", {}) if isinstance(meta, dict) else {}
        hermes_meta = meta.get("hermes", {}) if isinstance(meta, dict) else {}

        from weebot.domain.models.skill import SkillMetadata
        metadata = SkillMetadata(
            emoji=openclaw_meta.get("emoji") or meta.get("emoji") or frontmatter.get("emoji"),
            env=openclaw_meta.get("env", []) or meta.get("env", []),
            primary_env=openclaw_meta.get("primaryEnv") or meta.get("primaryEnv"),
            homepage=openclaw_meta.get("homepage") or meta.get("homepage") or frontmatter.get("homepage"),
            source=openclaw_meta.get("source") or meta.get("source") or frontmatter.get("source"),
            platforms=hermes_meta.get("platforms", []) or meta.get("platforms", []),
            config=hermes_meta.get("config", []) or meta.get("config", []),
            fallback_for_toolsets=hermes_meta.get("fallback_for_toolsets", []) or meta.get("fallback_for_toolsets", []),
            requires_toolsets=hermes_meta.get("requires_toolsets", []) or meta.get("requires_toolsets", []),
        )

        skill = Skill(
            name=frontmatter.get("name", filepath.parent.name),
            description=frontmatter.get("description", ""),
            content=content,
            metadata=metadata,
            source_path=str(filepath),
        )

        # Discover reference files for Progressive Disclosure (H1)
        # Set PrivateAttr directly (pydantic allows this for PrivateAttr fields)
        object.__setattr__(skill, "_reference_paths", _discover_references(filepath.parent))

        return skill

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def update_skill(self, skill: Skill) -> None:
        """Insert or replace *skill* in the in-memory registry by name."""
        self._skills[skill.name] = skill

    def list_skills(self) -> List[Skill]:
        return list(self._skills.values())

    def get_active_skills(self) -> List[Skill]:
        """Return skills that have all required environment variables."""
        return [s for s in self._skills.values() if s.is_ready()]

    def build_system_prompt_extensions(self, skill_names: Optional[List[str]] = None) -> str:
        """Build combined system prompt from selected or active skills."""
        if skill_names:
            skills = [self._skills[n] for n in skill_names if n in self._skills]
        else:
            skills = self.get_active_skills()
        if not skills:
            return ""
        parts = ["# Active Skills\n"]
        for skill in skills:
            parts.append(skill.to_system_prompt_extension())
        return "\n\n".join(parts)


# ── module-level helpers ────────────────────────────────────────────


def _discover_references(skill_dir: Path) -> list[str]:
    """List available reference file paths relative to *skill_dir*.

    Scans for a ``references/`` subdirectory and returns relative
    paths of all ``.md`` files found inside.  Does **not** load
    content — that happens lazily via ``Skill.get_reference()``.
    """
    ref_dir = skill_dir / "references"
    if not ref_dir.is_dir():
        return []
    return sorted(
        p.relative_to(skill_dir).as_posix()
        for p in ref_dir.rglob("*.md")
    )
