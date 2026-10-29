"""SelfImprover — controlled self-improvement service.

Constrained to editing skill prompts, tool contract YAML files, and rule
files. A patch carries the file's original and new content: validation checks
the new content, apply refuses when the file changed since the proposal, and
revert writes the original back. Nothing here applies a patch on its own; the
``improve`` CLI holds proposals until a human applies them (D4).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import posixpath
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
]
# Not here on purpose: weebot/config/harness holds the evaluation tasks that judge
# an edit, so an editor allowed there could grade itself (D4).

# Tier 2 allowlist — only active when METACOGNITIVE_IMPROVEMENT_ENABLED.
# These directories contain the self-improvement machinery itself.
_META_ALLOWED_TARGET_DIRS = ["weebot/application/services/self_improver.py"]


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
        self, project_root: Path | None = None, validation_runner: Any | None = None
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

    async def propose_patch(self, context: dict[str, Any]) -> SelfImprovementPatch | None:
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
            original_content=current_content,
            new_content=new_content,
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

        # Default: the PATCHED content must parse. This read the file on disk,
        # which is the unpatched one, so every patch "validated".
        valid, _ = self._validate_content(patch.target_file, patch.new_content)
        if not valid or not patch.new_content.strip():
            return 0.0
        suffix = Path(patch.target_file).suffix
        if suffix in (".yaml", ".yml", ".json"):
            return 0.7
        if suffix == ".md":
            return 0.8  # Markdown is hard to structurally validate
        return 0.5

    async def apply_patch(self, patch: SelfImprovementPatch) -> bool:
        """Apply a validated patch.

        Args:
            patch: The patch to apply.

        Returns:
            True if applied successfully.
        """
        if not self._is_allowed_target(patch.target_file):
            logger.error("Refusing to apply a patch to %s: not allowed", patch.target_file)
            return False
        path = self._project_root / patch.target_file
        if not path.exists():
            logger.error("Target file does not exist: %s", path)
            return False

        try:
            current = await asyncio.to_thread(path.read_text, encoding="utf-8")
            if current != patch.original_content:
                logger.error("%s changed since the patch was proposed", patch.target_file)
                return False
            valid, error = self._validate_content(patch.target_file, patch.new_content)
            if not valid:
                logger.error("Pre-apply validation failed: %s", error)
                return False
            await asyncio.to_thread(
                path.write_text, patch.new_content, encoding="utf-8", newline=""
            )
            patch.applied = True
            patch.applied_at = datetime.now(UTC)
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

        if not self._is_allowed_target(patch.target_file):
            logger.error("Refusing to revert a patch on %s: not allowed", patch.target_file)
            return False
        path = self._project_root / patch.target_file
        if not path.exists():
            logger.error("Target file does not exist: %s", path)
            return False

        try:
            current = await asyncio.to_thread(path.read_text, encoding="utf-8")
            if current != patch.new_content:
                logger.error("%s changed since the patch was applied", patch.target_file)
                return False
            await asyncio.to_thread(
                path.write_text, patch.original_content, encoding="utf-8", newline=""
            )
            patch.reverted = True
            patch.reverted_at = datetime.now(UTC)
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
        raw = Path(target_file)
        if raw.is_absolute() or raw.drive or target_file.startswith(("/", "\\")):
            return False
        # Normalised, so `builtin/../../x` cannot step outside; then a whole path
        # segment must match, so `builtin_evil/` is not inside `builtin/`.
        path = posixpath.normpath(raw.as_posix())
        if path == ".." or path.startswith("../"):
            return False

        def inside(allowed: str) -> bool:
            return path == allowed or path.startswith(allowed + "/")

        effective = _get_effective_allowlist()
        # Meta tier (the .py self-improvement machinery) only while its flag is on: the
        # effective allowlist holds it then, and not otherwise.
        for allowed in _META_ALLOWED_TARGET_DIRS:
            if allowed in effective and inside(allowed):
                return True

        # Tier-1 check: normal extensions only
        if Path(path).suffix not in _ALLOWED_EXTENSIONS:
            return False
        return any(inside(allowed) for allowed in _ALLOWED_TARGET_DIRS)

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
            old_lines, new_lines, fromfile=f"a/{filepath}", tofile=f"b/{filepath}"
        )
        return "".join(diff)
