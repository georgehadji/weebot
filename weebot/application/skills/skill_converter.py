"""SkillConverter — converts external skill formats to Weebot format (Enhancement 10).

Detects source format (Manus, MyManus, AgenticSeek, OpenClaw), transforms
tool references, and writes a standard Weebot skill package (manifest.json +
prompt.md) to the skills directory.

The converter is registered in SkillPackager.install_from_path() so that
any external skill is automatically converted on import.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import yaml

from weebot.application.skills.format_detector import FormatDetector
from weebot.domain.models.skill_source import SourceFormat

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "skill_converter.yaml"
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "builtin"


class ConversionReport:
    """Result of converting a skill."""

    def __init__(
        self,
        success: bool,
        source_path: str,
        target_path: Optional[str] = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.success = success
        self.source_path = source_path
        self.target_path = target_path
        self.errors = errors or []
        self.warnings = warnings or []


class SkillConverter:
    """Convert skills from external formats to Weebot format.

    Args:
        skills_dir: Target directory for converted skills.
        config_path: Path to tool mapping config.
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        self._skills_dir = skills_dir or SKILLS_DIR
        self._config = self._load_config(config_path or CONFIG_PATH)

    @staticmethod
    def _load_config(path: Path) -> dict:
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("Failed to load converter config: %s", exc)
            return {"tool_mappings": {}, "manifest_template": {}}

    def convert(self, source_path: Path) -> ConversionReport:
        """Detect and convert a skill at *source_path* to Weebot format.

        Returns a ConversionReport with success/failure details.
        """
        source = FormatDetector.detect(source_path)

        if source.format == SourceFormat.UNKNOWN:
            return ConversionReport(
                success=False,
                source_path=str(source_path),
                errors=[f"Cannot determine format for {source_path}"],
            )

        if source.format == SourceFormat.WEEBOT:
            return ConversionReport(
                success=True,
                source_path=str(source_path),
                warnings=["Already in Weebot format — no conversion needed"],
            )

        handlers = {
            SourceFormat.MANUS: self._convert_manus,
            SourceFormat.OPENCLAW: self._convert_manus,
            SourceFormat.MYMANUS: self._convert_mymanus,
            SourceFormat.AGENTICSEEK: self._convert_agenticseek,
        }

        handler = handlers.get(source.format)
        if handler is None:
            return ConversionReport(
                success=False,
                source_path=str(source_path),
                errors=[f"No converter for format: {source.format}"],
            )

        try:
            return handler(source_path, source.name)
        except Exception as exc:
            return ConversionReport(
                success=False,
                source_path=str(source_path),
                errors=[f"Conversion failed: {exc}"],
            )

    def _convert_manus(self, source_path: Path, name: str) -> ConversionReport:
        """Convert Manus/OpenClaw SKILL.md with YAML frontmatter."""
        skill_md = source_path / "SKILL.md" if source_path.is_dir() else source_path
        if not skill_md.exists():
            return ConversionReport(success=False, source_path=str(source_path), errors=["SKILL.md not found"])

        content = skill_md.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        frontmatter = {}
        prompt_body = content  # fallback: entire file

        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                prompt_body = parts[2].strip()
            except Exception:
                prompt_body = content

        # Map tools
        raw_tools = frontmatter.get("tools", [])
        tool_map = self._config.get("tool_mappings", {}).get("manus", {})
        mapped_tools = [tool_map.get(t, t) for t in raw_tools]

        manifest = {
            "name": frontmatter.get("name", name),
            "version": str(frontmatter.get("version", "1.0.0")),
            "description": frontmatter.get("description", f"Converted from Manus: {name}"),
            "author": "Import (Manus)",
            "requires": list(dict.fromkeys(mapped_tools)),
            "prompt_file": "prompt.md",
        }

        return self._write_skill(source_path, name, manifest, prompt_body)

    def _convert_mymanus(self, source_path: Path, name: str) -> ConversionReport:
        """Convert MyManus plugin.json + SKILL.md."""
        plugin_path = source_path / "plugin.json"
        skill_md_path = source_path / "SKILL.md"

        plugin = {}
        if plugin_path.exists():
            plugin = json.loads(plugin_path.read_text(encoding="utf-8"))

        prompt_body = ""
        if skill_md_path.exists():
            prompt_body = skill_md_path.read_text(encoding="utf-8")
            # Strip YAML frontmatter if present
            parts = prompt_body.split("---", 2)
            if len(parts) >= 3:
                prompt_body = parts[2].strip()

        tool_map = self._config.get("tool_mappings", {}).get("mymanus", {})
        raw_tools = plugin.get("tools", [])
        mapped_tools = [tool_map.get(t, t) for t in raw_tools]

        manifest = {
            "name": plugin.get("name", name),
            "version": str(plugin.get("version", "1.0.0")),
            "description": plugin.get("description", f"Converted from MyManus: {name}"),
            "author": "Import (MyManus)",
            "requires": list(dict.fromkeys(mapped_tools)),
            "prompt_file": "prompt.md",
        }

        return self._write_skill(source_path, name, manifest, prompt_body)

    def _convert_agenticseek(self, source_path: Path, name: str) -> ConversionReport:
        """Convert AgenticSeek .txt file with XML tags."""
        content = source_path.read_text(encoding="utf-8")

        # Strip XML tags, keep inner text
        prompt_body = re.sub(r"<[^>]+>", "", content).strip()

        # Extract tool references from <actions> blocks
        tool_map = self._config.get("tool_mappings", {}).get("agenticseek", {})
        found_tools = list(tool_map.values())

        manifest = {
            "name": name,
            "version": "1.0.0",
            "description": f"Converted from AgenticSeek: {name}",
            "author": "Import (AgenticSeek)",
            "requires": list(dict.fromkeys(found_tools)),
            "prompt_file": "prompt.md",
        }

        return self._write_skill(source_path, name, manifest, prompt_body)

    def _write_skill(
        self, source_path: Path, name: str, manifest: dict, prompt_body: str,
    ) -> ConversionReport:
        """Write manifest.json + prompt.md to target directory."""
        target_dir = self._skills_dir / name

        if target_dir.exists():
            return ConversionReport(
                success=False,
                source_path=str(source_path),
                errors=[f"Target directory already exists: {target_dir}"],
            )

        target_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        # Write prompt
        (target_dir / "prompt.md").write_text(prompt_body, encoding="utf-8")

        logger.info("Converted skill %s → %s (%d chars)", name, target_dir, len(prompt_body))
        return ConversionReport(
            success=True,
            source_path=str(source_path),
            target_path=str(target_dir),
        )
