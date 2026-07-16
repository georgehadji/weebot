"""HarnessOptimizationTarget — OptimizationTarget wrapping HarnessConfig.

Bridges between the generic optimization loop and weebot's versioned
HarnessConfig YAML files.  The ``content`` property serializes the
instruction/runtime-control surfaces for the optimizer LLM; edits are
applied as YAML mutations and saved as new versioned files.

Version mapping:
  - HarnessConfig.version is a string like ``"0.2.0"``
  - OptimizationTarget.version is an integer counter
  - The counter is stored as the patch component of the YAML version
    (e.g. ``"0.2.5"`` after 5 edit cycles)
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

import yaml

from weebot.application.ports.optimization_target_port import OptimizationTarget
from weebot.config.harness.schema import HarnessConfig

logger = logging.getLogger(__name__)


class HarnessOptimizationTarget(OptimizationTarget):
    """OptimizationTarget for ``HarnessConfig`` artifacts.

    Usage::

        target = HarnessOptimizationTarget(
            harness_path="weebot/config/harness/v0.2.0.yaml",
            output_dir="weebot/config/harness/evolved/",
        )
        cfg = await target.load()
        candidate = await target.apply_edits([...])
        saved = await target.save(candidate)
    """

    def __init__(
        self,
        harness_path: str | Path = "weebot/config/harness/v0.2.0.yaml",
        output_dir: str | Path | None = None,
        model_id: str | None = None,
    ) -> None:
        self._model_id = model_id
        if model_id:
            from weebot.config.model_refs import sanitize_model_id
            safe_name = sanitize_model_id(model_id)
            models_dir = Path("weebot/config/harness/models")
            models_dir.mkdir(parents=True, exist_ok=True)
            harness_path = models_dir / f"{safe_name}.yaml"
            if not harness_path.exists():
                # First run — copy the default harness as starting point
                default = Path("weebot/config/harness/v0.2.0.yaml")
                if default.exists():
                    import shutil
                    shutil.copy(default, harness_path)
            output_dir = output_dir or models_dir / f"{safe_name}_evolved"
        self._harness_path = Path(harness_path)
        self._output_dir = (
            Path(output_dir) if output_dir
            else self._harness_path.parent / "evolved"
        )
        self._current: HarnessConfig | None = None
        self._version: int = 0  # integer counter, bumped on save
        self._base_version_str: str = "0.0.0"

    # ── OptimizationTarget properties ─────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """Whether the harness has been loaded from disk."""
        return self._current is not None

    @property
    def name(self) -> str:
        return self._current.version if self._current else "unloaded"

    @property
    def version(self) -> int:
        return self._version

    @property
    def content(self) -> str:
        """Serialize the harness config for the optimizer LLM.

        Includes only the behavioral surfaces (instructions, runtime_control)
        plus structural knobs (skill_retrieval, trajectory thresholds).
        """
        if self._current is None:
            return ""

        parts = [
            f"## Harness: {self._current.version}",
            f"Description: {self._current.description}",
            "",
            "### Behavioral Instructions",
        ]

        ic = self._current.instructions
        parts.append(f"- bootstrap: {ic.bootstrap or '(empty)'}")
        parts.append(f"- execution: {ic.execution or '(empty)'}")
        parts.append(f"- verification: {ic.verification or '(empty)'}")
        parts.append(f"- failure_recovery: {ic.failure_recovery or '(empty)'}")

        rc = self._current.runtime_control
        parts.extend([
            "",
            "### Runtime Control",
            f"- enabled: {rc.enabled}",
            f"- max_recent_tool_errors: {rc.max_recent_tool_errors}",
            f"- max_total_tool_messages: {rc.max_total_tool_messages}",
        ])

        sk = self._current.skill_retrieval
        parts.extend([
            "",
            "### Skill Retrieval",
            f"- enabled: {sk.enabled}",
            f"- top_k: {sk.top_k}",
        ])

        tr = self._current.trajectory
        parts.extend([
            "",
            "### Trajectory Regulation",
            f"- repetition_threshold: {tr.repetition_threshold}",
            f"- stagnation_window: {tr.stagnation_window}",
        ])

        ss = self._current.skill_selection
        if ss.active_skills:
            parts.extend([
                "",
                "### Active Skills",
                f"- {', '.join(ss.active_skills)}",
            ])

        return "\n".join(parts)

    # ── OptimizationTarget methods ────────────────────────────────────

    async def load(self) -> HarnessConfig:
        """Load the current harness from its YAML file."""
        if not self._harness_path.exists():
            raise FileNotFoundError(
                f"Harness config not found: {self._harness_path}"
            )

        cfg = HarnessConfig.load(self._harness_path)
        self._current = cfg
        self._base_version_str = cfg.version

        # Parse integer version from patch component (e.g. "0.2.3" → 3)
        parts = cfg.version.split(".")
        try:
            self._version = int(parts[-1]) if len(parts) >= 3 else 0
        except (ValueError, IndexError):
            self._version = 0

        logger.info("Loaded harness %s (v=%d)", cfg.version, self._version)
        return cfg

    async def apply_edits(
        self, edits: list[dict[str, Any]],
    ) -> HarnessConfig:
        """Apply edits to the current harness config.

        Each edit dict must have:
          - ``target``: dot-separated path (e.g. ``"instructions.bootstrap"``)
          - ``value``: the new value

        Returns a new HarnessConfig with edits applied (does NOT persist).
        """
        if self._current is None:
            raise RuntimeError("No harness loaded — call load() first")

        data = self._current.model_dump()

        for edit in edits:
            target = edit.get("target", "")
            value = edit.get("value")

            if not target:
                logger.warning("Skipping edit with empty target")
                continue

            # ── Structural edits (middleware add, subagent add) ────
            if target.startswith("middleware.add:") or target.startswith("subagents.add:"):
                prefix, name = target.split(":", 1)
                if prefix == "middleware.add":
                    if "middleware" not in data:
                        data["middleware"] = []
                    entry = value if isinstance(value, dict) else {"name": name, "trigger": str(value), "action": str(value)}
                    data["middleware"].append(entry)
                    logger.info("Applied structural edit: added middleware '%s'", name)
                elif prefix == "subagents.add":
                    if "subagents" not in data:
                        data["subagents"] = {"definitions": []}
                    if "definitions" not in data["subagents"]:
                        data["subagents"]["definitions"] = []
                    entry = value if isinstance(value, dict) else {"name": name, "role": str(value)}
                    data["subagents"]["definitions"].append(entry)
                    logger.info("Applied structural edit: added subagent '%s'", name)
                continue

            # ── Standard field edits (dot-separated path) ──────────
            parts = target.split(".")
            current = data
            for part in parts[:-1]:
                if part not in current:
                    logger.warning("Edit target %s not found — skipping", target)
                    break
                current = current[part]
            else:
                leaf = parts[-1]
                if leaf in current:
                    old_val = current[leaf]
                    current[leaf] = value
                    logger.info(
                        "Applied edit: %s = %r → %r", target, old_val, value,
                    )
                else:
                    logger.warning("Field %s not found in %s — skipping", leaf, target)

        return HarnessConfig.model_validate(data)

    async def save(self, candidate: HarnessConfig) -> HarnessConfig:
        """Persist an accepted candidate as a new versioned YAML file.

        Bumps the patch version, writes to output_dir, and updates _current.
        """
        self._version += 1
        new_version = self._bump_patch(candidate.version)
        candidate = candidate.model_copy(update={
            "version": new_version,
            "evolved_from": self._current.version if self._current else None,
        })

        self._output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._output_dir / f"v{new_version}.yaml"

        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                candidate.model_dump(exclude_none=True),
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

        self._current = candidate
        logger.info("Saved harness %s → %s", new_version, out_path)
        return candidate

    async def rollback(self) -> HarnessConfig:
        """Revert to the previously saved version by re-loading from disk.

        If no evolved versions exist, re-loads the base harness.
        """
        if self._version <= 0:
            return await self.load()

        prev_version = f"{self._base_version_str.rsplit('.', 1)[0]}.{self._version - 1}"
        prev_path = self._output_dir / f"v{prev_version}.yaml"

        if prev_path.exists():
            cfg = HarnessConfig.load(prev_path)
        else:
            cfg = await self.load()

        self._current = cfg
        self._version -= 1
        logger.info("Rolled back to %s", cfg.version)
        return cfg

    async def close(self) -> None:
        pass  # No resources to release

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _bump_patch(version_str: str) -> str:
        """Increment the patch component of a semver string.

        >>> _bump_patch("0.2.0")
        "0.2.1"
        """
        parts = version_str.split(".")
        try:
            patch = int(parts[-1]) + 1
            parts[-1] = str(patch)
        except (ValueError, IndexError):
            parts.append("1")
        return ".".join(parts)
