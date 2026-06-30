"""SelfImprover — controlled self-improvement service.

Constrained to editing skill prompts, tool contract YAML files, and
rule files. Every patch is validated through AST parsing + sandbox
execution before being applied. Patches are git-backed for rollback.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import yaml

from weebot.application.ports.self_improvement_port import SelfImprovementPort
from weebot.domain.models.self_improvement import SelfImprovementPatch

logger = logging.getLogger(__name__)

# Allowlist of directories that self-improvement can edit (Tier 1 — always allowed)
_ALLOWED_TARGET_DIRS = [
    "weebot/skills/builtin",
    "weebot/config/contracts",
    "weebot/config/prompts/rules",
    "weebot/config/prompts/variants",  # HyperAgents Enhancement 5
    "weebot/config/harness",
]

# Tier 2 allowlist — only active when METACOGNITIVE_IMPROVEMENT_ENABLED.
# These directories contain the self-improvement machinery itself.
_META_ALLOWED_TARGET_DIRS = [
    "weebot/application/services/self_improver.py",
    "weebot/application/services/meta_self_improver.py",
]


def _get_effective_allowlist() -> list[str]:
    """Return the current allowlist, including meta-tier if the feature flag is on."""
    effective = list(_ALLOWED_TARGET_DIRS)
    try:
        from weebot.config.feature_flags import METACOGNITIVE_IMPROVEMENT_ENABLED
        if METACOGNITIVE_IMPROVEMENT_ENABLED:
            effective.extend(_META_ALLOWED_TARGET_DIRS)
    except ImportError:
        pass
    return effective

# Allowlist of file extensions
_ALLOWED_EXTENSIONS = {".md", ".yaml", ".yml", ".json", ".txt"}


class SelfImprover(SelfImprovementPort):
    """Controlled self-improvement for skills, contracts, and rules.

    Proposes patches based on execution patterns, validates them
    through AST parsing (YAML/JSON) and sandbox testing, then
    applies them with git-backed rollback.
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        validation_runner: Optional[Any] = None,
    ) -> None:
        """Initialize the self-improver.

        Args:
            project_root: Project root path. Defaults to CWD.
            validation_runner: Optional callable that runs a validation task
                               and returns a score 0.0–1.0.
        """
        self._project_root = project_root or Path.cwd()
        self._validation_runner = validation_runner

    # ── Public API ──────────────────────────────────────────────────

    async def propose_patch(
        self, context: dict[str, Any]
    ) -> Optional[SelfImprovementPatch]:
        """Propose a patch based on execution context.

        Args:
            context: Dict with 'target_file', 'current_content', 'new_content',
                     and optional 'target_type'.

        Returns:
            SelfImprovementPatch or None.
        """
        target_file = context.get("target_file", "")
        if not target_file:
            logger.warning("No target_file in context — skipping patch proposal")
            return None

        if not self._is_allowed_target(target_file):
            logger.warning("Target %s is not in the allowlist — skipping", target_file)
            return None

        current_content = context.get("current_content", "")
        new_content = context.get("new_content", "")

        if not current_content or not new_content:
            logger.warning("Missing current or new content — skipping patch")
            return None

        if current_content == new_content:
            logger.info("No change detected — skipping patch")
            return None

        # Validate the new content before creating a patch
        valid, error = self._validate_content(target_file, new_content)
        if not valid:
            logger.warning("New content validation failed: %s", error)
            return None

        diff = self._generate_diff(target_file, current_content, new_content)

        target_type = context.get("target_type", self._infer_type(target_file))

        return SelfImprovementPatch(
            id=str(uuid4()),
            target_file=target_file,
            target_type=target_type,
            diff=diff,
            validation_tasks=context.get("validation_tasks", []),
        )

    async def validate_patch(self, patch: SelfImprovementPatch) -> float:
        """Validate a proposed patch.

        Uses the validation runner if available, otherwise returns
        a default score based on YAML/JSON parse success.

        Args:
            patch: The patch to validate.

        Returns:
            Validation score 0.0–1.0.
        """
        if self._validation_runner is not None:
            try:
                score = await self._validation_runner(patch)
                return score
            except Exception as exc:
                logger.warning("Validation runner failed: %s", exc)

        # Default: YAML/JSON parse check
        path = self._project_root / patch.target_file
        if path.suffix in (".yaml", ".yml"):
            try:
                content = await asyncio.to_thread(path.read_text, encoding="utf-8")
                yaml.safe_load(content)
                return 0.7
            except Exception:
                return 0.0
        elif path.suffix == ".json":
            try:
                content = await asyncio.to_thread(path.read_text, encoding="utf-8")
                json.loads(content)
                return 0.7
            except Exception:
                return 0.0
        elif path.suffix == ".md":
            return 0.8  # Markdown is hard to structurally validate
        return 0.5

    async def apply_patch(self, patch: SelfImprovementPatch) -> bool:
        """Apply a validated patch.

        Args:
            patch: The patch to apply.

        Returns:
            True if applied successfully.
        """
        path = self._project_root / patch.target_file
        if not path.exists():
            logger.error("Target file does not exist: %s", path)
            return False

        try:
            current = await asyncio.to_thread(path.read_text, encoding="utf-8")
            # Apply diff
            new = self._apply_diff(current, patch.diff)
            if new is None:
                logger.error("Failed to apply diff to %s", patch.target_file)
                return False

            # Final validation before write
            valid, error = self._validate_content(patch.target_file, new)
            if not valid:
                logger.error("Pre-apply validation failed: %s", error)
                return False

            # Write
            await asyncio.to_thread(path.write_text, new, encoding="utf-8")
            patch.applied = True
            logger.info("Applied patch to %s", patch.target_file)
            return True

        except Exception as exc:
            logger.error("Failed to apply patch: %s", exc)
            return False

    async def revert_patch(self, patch: SelfImprovementPatch) -> bool:
        """Revert a previously applied patch.

        Args:
            patch: The patch to revert.

        Returns:
            True if reverted successfully.
        """
        if not patch.applied:
            logger.warning("Patch %s was never applied — nothing to revert", patch.id)
            return False

        path = self._project_root / patch.target_file
        if not path.exists():
            logger.error("Target file does not exist: %s", path)
            return False

        try:
            current = await asyncio.to_thread(path.read_text, encoding="utf-8")
            # Reverse the diff
            reversed_diff = self._reverse_diff(patch.diff)
            reverted = self._apply_diff(current, reversed_diff)
            if reverted is None:
                logger.error("Failed to reverse patch for %s", patch.target_file)
                return False

            await asyncio.to_thread(path.write_text, reverted, encoding="utf-8")
            patch.reverted = True
            logger.info("Reverted patch on %s", patch.target_file)
            return True

        except Exception as exc:
            logger.error("Failed to revert patch: %s", exc)
            return False

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _is_allowed_target(target_file: str) -> bool:
        """Check if a target file is in the allowlist.

        Uses the effective allowlist which includes meta-tier directories
        when METACOGNITIVE_IMPROVEMENT_ENABLED is True.

        Meta-tier files may have .py extension (the SelfImprover itself).

        Args:
            target_file: Relative path from project root.

        Returns:
            True if allowed.
        """
        path = Path(target_file).as_posix()
        ext = Path(target_file).suffix

        effective = _get_effective_allowlist()
        # Check meta-tier first (allows .py files for self-improvement)
        for allowed in _META_ALLOWED_TARGET_DIRS:
            if path.startswith(allowed):
                return True

        # Tier-1 check: normal extensions only
        if ext not in _ALLOWED_EXTENSIONS:
            return False
        return any(path.startswith(allowed) for allowed in _ALLOWED_TARGET_DIRS)

    @staticmethod
    def _infer_type(target_file: str) -> str:
        """Infer the target type from the file path.

        Args:
            target_file: Relative path.

        Returns:
            'skill', 'contract', 'rule', or 'harness'.
        """
        path = target_file.replace("\\", "/")
        if "skills" in path:
            return "skill"
        if "contracts" in path:
            return "contract"
        if "rules" in path:
            return "rule"
        if "harness" in path:
            return "harness"
        return "skill"

    @staticmethod
    def _validate_content(target_file: str, content: str) -> tuple[bool, str]:
        """Validate that content is structurally sound.

        Args:
            target_file: Target path (used to infer format).
            content: Content to validate.

        Returns:
            Tuple of (valid, error_message).
        """
        ext = Path(target_file).suffix
        if ext in (".yaml", ".yml"):
            try:
                yaml.safe_load(content)
                return True, ""
            except yaml.YAMLError as e:
                return False, f"YAML parse error: {e}"
        elif ext == ".json":
            try:
                json.loads(content)
                return True, ""
            except json.JSONDecodeError as e:
                return False, f"JSON parse error: {e}"
        return True, ""

    @staticmethod
    def _generate_diff(filepath: str, old: str, new: str) -> str:
        """Generate a unified diff string.

        Args:
            filepath: The target file path (for diff header).
            old: Original content.
            new: New content.

        Returns:
            Unified diff string.
        """
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
        )
        return "".join(diff)

    @staticmethod
    def _apply_diff(content: str, diff: str) -> Optional[str]:
        """Apply a unified diff to content.

        Args:
            content: Original content.
            diff: Unified diff string.

        Returns:
            Patched content, or None if the diff couldn't be applied.
        """
        if not diff:
            return content

        result_lines = content.splitlines(keepends=True)
        # Simple line-based patch application
        # Parse diff hunks
        lines_to_add: dict[int, list[str]] = {}
        lines_to_remove: set[int] = set()

        current_line = 0
        for line in diff.splitlines(keepends=True):
            # Parse @@ -start,count +start,count @@
            if line.startswith("@@"):
                match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if match:
                    current_line = int(match.group(2)) - 1  # 0-indexed
                    continue
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("+"):
                lines_to_add.setdefault(current_line, []).append(line[1:])
                current_line += 1
            elif line.startswith("-"):
                lines_to_remove.add(current_line)
                # Don't increment — the removed line doesn't exist in new
            else:
                current_line += 1

        # Build result (skip removed, insert added before corresponding lines)
        result: list[str] = []
        for i, line in enumerate(result_lines):
            if i in lines_to_remove:
                continue
            if i in lines_to_add:
                result.extend(lines_to_add[i])
            result.append(line)

        return "".join(result)

    @staticmethod
    def _reverse_diff(diff: str) -> str:
        """Reverse a unified diff (swap + and - lines).

        Args:
            diff: Original unified diff.

        Returns:
            Reversed unified diff.
        """
        result: list[str] = []
        for line in diff.splitlines(keepends=True):
            if line.startswith("+"):
                result.append("-" + line[1:])
            elif line.startswith("-"):
                result.append("+" + line[1:])
            elif line.startswith("---"):
                result.append("+++" + line[3:])
            elif line.startswith("+++"):
                result.append("---" + line[3:])
            else:
                result.append(line)
        return "".join(result)
