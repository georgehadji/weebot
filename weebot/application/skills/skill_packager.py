"""SkillPackager — installs, validates, and loads modular skill packages.

Each skill is a folder containing:
- manifest.json  — metadata, dependencies, entry points
- prompt.md      — system prompt injected into the executor
- tools.py       — optional custom tool definitions (loaded dynamically)

The packager validates manifests, resolves dependencies, and loads
skills into the ToolCollection and SkillRegistry.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from weebot.application.skills.skill_registry import SkillRegistry
from weebot.domain.models.skill import Skill, SkillMetadata
from weebot.tools.base import BaseTool, ToolCollection

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "builtin"


class SkillPackager:
    """Manage skill installation, validation, and dynamic loading.

    Args:
        skills_dir: Base directory for skill packages.
                    Defaults to weebot/skills/builtin/.
        registry: Optional SkillRegistry to register into.
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        registry: Optional[SkillRegistry] = None,
    ) -> None:
        self._skills_dir = skills_dir or _SKILLS_DIR
        self._registry = registry or SkillRegistry()

    def discover_all(self) -> list[Path]:
        """Return paths to all skill directories with valid manifests."""
        skills = []
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir():
                manifest_path = entry / "manifest.json"
                if manifest_path.exists():
                    skills.append(entry)
        return skills

    def load_manifest(self, skill_dir: Path) -> Optional[dict]:
        """Load and validate a skill manifest.

        Args:
            skill_dir: Path to the skill directory.

        Returns:
            Parsed manifest dict, or None if invalid.
        """
        manifest_path = skill_dir / "manifest.json"
        if not manifest_path.exists():
            logger.warning("No manifest.json in %s", skill_dir)
            return None

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Invalid manifest in %s: %s", skill_dir, exc)
            return None

        required = {"name", "prompt_file"}
        missing = required - set(manifest.keys())
        if missing:
            logger.warning(
                "Manifest in %s missing required fields: %s",
                skill_dir, missing,
            )
            return None

        return manifest

    def load_skill(self, skill_dir: Path) -> Optional[Skill]:
        """Load a skill from its directory into the registry.

        Args:
            skill_dir: Path to the skill directory.

        Returns:
            Skill instance, or None if loading failed.
        """
        manifest = self.load_manifest(skill_dir)
        if manifest is None:
            return None

        name = manifest["name"]
        prompt_file = manifest["prompt_file"]
        prompt_path = skill_dir / prompt_file

        if not prompt_path.exists():
            logger.warning("Prompt file %s not found for skill %s", prompt_path, name)
            return None

        try:
            prompt_content = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read prompt for skill %s: %s", name, exc)
            return None

        description = manifest.get("description", "")
        emoji = manifest.get("emoji", "")

        skill = Skill(
            name=name,
            description=description,
            content=prompt_content,
            metadata=SkillMetadata(emoji=emoji) if emoji else None,
        )

        self._registry.register(skill)
        logger.info("Loaded skill: %s from %s", name, skill_dir)
        return skill

    def load_custom_tools(self, skill_dir: Path) -> list[BaseTool]:
        """Load custom tools from skill_dir/tools.py, if it exists.

        Args:
            skill_dir: Path to the skill directory.

        Returns:
            List of BaseTool instances, or empty list.
        """
        tools_path = skill_dir / "tools.py"
        if not tools_path.exists():
            return []

        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            f"skill_tools_{skill_dir.name}", tools_path
        )
        if spec is None or spec.loader is None:
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        tools = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseTool)
                and attr is not BaseTool
            ):
                tools.append(attr())
                logger.debug(
                    "Loaded custom tool %s from %s", attr.__name__, tools_path
                )

        return tools

    def install_from_path(self, source: Path) -> Optional[Skill]:
        """Install a skill from an external path by copying its directory.

        Args:
            source: Path to skill directory (with manifest.json).

        Returns:
            Loaded Skill, or None on failure.
        """
        manifest = self.load_manifest(source)
        if manifest is None:
            return None

        name = manifest["name"]
        target = self._skills_dir / name

        import shutil
        if target.exists():
            logger.warning("Skill %s already installed at %s", name, target)
            return None

        shutil.copytree(source, target)
        logger.info("Installed skill %s → %s", name, target)
        return self.load_skill(target)
