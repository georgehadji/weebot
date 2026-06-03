"""FormatDetector — determines the source format of a skill file or directory.

Reads the filesystem to detect which of the 5 supported formats a skill
uses.  Returns a SkillSource with the detected format and confidence score.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from weebot.domain.models.skill_source import SkillSource, SourceFormat

logger = logging.getLogger(__name__)


class FormatDetector:
    """Detect skill format from file patterns.

    Detection logic (checked in order):
    1. WEEBOT — manifest.json exists in a directory
    2. MYMANUS — plugin.json exists in a directory
    3. MANUS / OPENCLAW — SKILL.md with YAML frontmatter
    4. AGENTICSEEK — .txt file with <agent_loop> or <system_capability> tags
    5. UNKNOWN — no pattern matched
    """

    @staticmethod
    def detect(path: Path) -> SkillSource:
        """Detect the format of a skill at *path*.

        *path* may be a directory or a single file.
        """
        if not path.exists():
            return SkillSource(path=str(path), format=SourceFormat.UNKNOWN, confidence=0.0)

        if path.is_dir():
            return FormatDetector._detect_directory(path)
        else:
            return FormatDetector._detect_file(path)

    @staticmethod
    def _detect_directory(path: Path) -> SkillSource:
        # Check for Weebot format (manifest.json)
        manifest = path / "manifest.json"
        if manifest.exists():
            try:
                import json
                data = json.loads(manifest.read_text(encoding="utf-8"))
                name = data.get("name", path.name)
                return SkillSource(
                    path=str(path),
                    format=SourceFormat.WEEBOT,
                    name=name,
                    confidence=1.0,
                )
            except Exception:
                pass

        # Check for MyManus format (plugin.json)
        plugin = path / "plugin.json"
        if plugin.exists():
            try:
                import json
                data = json.loads(plugin.read_text(encoding="utf-8"))
                name = data.get("name", data.get("id", path.name))
                return SkillSource(
                    path=str(path),
                    format=SourceFormat.MYMANUS,
                    name=name,
                    confidence=0.95,
                )
            except Exception:
                pass

        # Check for Manus / OpenClaw format (SKILL.md with YAML frontmatter)
        skill_md = path / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            if content.startswith("---"):
                return SkillSource(
                    path=str(path),
                    format=SourceFormat.MANUS,
                    name=path.name,
                    confidence=0.9,
                )

        return SkillSource(
            path=str(path), format=SourceFormat.UNKNOWN, name=path.name, confidence=0.0,
        )

    @staticmethod
    def _detect_file(path: Path) -> SkillSource:
        name = path.stem

        # AgenticSeek format: .txt file with XML tags
        if path.suffix == ".txt":
            content = path.read_text(encoding="utf-8", errors="replace")
            if "<agent_loop>" in content or "<system_capability>" in content:
                return SkillSource(
                    path=str(path),
                    format=SourceFormat.AGENTICSEEK,
                    name=name,
                    confidence=0.95,
                )

        # Single SKILL.md with frontmatter
        if path.name == "SKILL.md" and content.startswith("---"):
            return SkillSource(
                path=str(path),
                format=SourceFormat.MANUS,
                name=path.parent.name,
                confidence=0.9,
            )

        return SkillSource(
            path=str(path), format=SourceFormat.UNKNOWN, name=name, confidence=0.0,
        )
