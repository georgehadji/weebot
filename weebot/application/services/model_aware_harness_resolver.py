"""ModelAwareHarnessResolver — resolves model-specific harness instruction overlays.

The resolver loads a directory of overlay YAML files (one per model family)
and merges them into the base HarnessConfig at runtime.  This enables:

1. **Per-step resolution**: the active model's instructions are resolved
   before each executor step, so model-cascade fallbacks get appropriate
   instructions.

2. **Per-model optimization**: Self-Harness can evolve different overlays
   for different models, reflecting the paper's finding that harness
   effectiveness is model-specific.

Usage::

    resolver = ModelAwareHarnessResolver(
        base_config=HarnessConfig.load("config/harness/v0.2.0.yaml"),
        overlays_dir="config/harness/overlays/",
    )
    resolved = resolver.resolve("gpt-4o-mini")
    # Returns base config merged with gpt-4o.yaml overlay (if any)
    block = resolver.resolve_instruction_block("qwen/qwen3-35b")
    # Returns assembled instruction block for the resolved config
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Optional

import yaml

from weebot.config.harness.schema import HarnessConfig
from weebot.domain.models.harness_instructions import InstructionConfig
from weebot.application.services.harness_prompt_assembler import (
    HarnessPromptAssembler,
)

logger = logging.getLogger(__name__)


class ModelAwareHarnessResolver:
    """Resolves model-specific harness instruction overlays.

    Overlays are YAML files in ``overlays_dir``, each named by model ID
    pattern (e.g. ``gpt-4o.yaml``, ``qwen3.yaml``).  When resolving for a
    specific model ID, the most specific matching overlay is merged into
    the base config.

    Only the ``instructions`` section is overlaid — structural layers
    (canonicalizer, skill_retrieval, trajectory) are left unchanged.
    """

    def __init__(
        self,
        base_config: HarnessConfig | None = None,
        overlays_dir: str | Path = "weebot/config/harness/overlays/",
    ) -> None:
        self._base = base_config or HarnessConfig.default()
        self._overlays_dir = Path(overlays_dir)
        self._overlays: dict[str, dict] = {}  # pattern -> overlay data
        self._loaded: bool = False

    def set_base(self, config: HarnessConfig) -> None:
        """Update the base harness config (called when harness evolves)."""
        self._base = config

    def load_overlays(self) -> None:
        """Scan the overlays directory and load all YAML files."""
        self._overlays.clear()
        if not self._overlays_dir.exists():
            logger.info("No overlays directory at %s", self._overlays_dir)
            self._loaded = True
            return

        for fpath in sorted(self._overlays_dir.glob("*.yaml")):
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                pattern = data.pop("model_pattern", fpath.stem)
                self._overlays[pattern] = data
                logger.debug(
                    "Loaded overlay %s → pattern %r", fpath.name, pattern,
                )
            except Exception as exc:
                logger.warning("Failed to load overlay %s: %s", fpath.name, exc)

        self._loaded = True
        logger.info(
            "Loaded %d harness overlays from %s",
            len(self._overlays), self._overlays_dir,
        )

    def resolve(self, model_id: str) -> HarnessConfig:
        """Resolve the harness config for a given model ID.

        Merges the best-matching overlay's instructions into the base config.
        If no overlay matches, returns the base config unchanged.
        """
        if not self._loaded:
            self.load_overlays()

        overlay = self._find_best_overlay(model_id)
        if overlay is None:
            return self._base

        # Merge only the instructions section
        overlay_instructions = overlay.get("instructions", {})
        if not overlay_instructions:
            return self._base

        # Filter overlay keys to only valid InstructionConfig fields
        valid_fields = set(InstructionConfig.model_fields.keys())
        filtered = {
            k: v for k, v in overlay_instructions.items()
            if k in valid_fields
        }
        if not filtered:
            logger.warning(
                "Overlay for %s has no valid instruction fields (got: %s)",
                model_id, list(overlay_instructions.keys()),
            )
            return self._base

        current_instructions = self._base.instructions.model_dump()
        merged_instructions = {**current_instructions, **filtered}

        try:
            return self._base.model_copy(update={
                "instructions": InstructionConfig(**merged_instructions),
            })
        except Exception as exc:
            logger.warning(
                "Failed to merge overlay for %s: %s — returning base config",
                model_id, exc,
            )
            return self._base

    def resolve_instruction_block(self, model_id: str) -> str:
        """Resolve and assemble the instruction block for a model.

        Returns an empty string when base instructions are all empty.
        """
        resolved = self.resolve(model_id)
        return HarnessPromptAssembler.assemble(
            instructions=resolved.instructions,
            runtime_control=resolved.runtime_control,
            subagents=resolved.subagents,
            skill_selection=resolved.skill_selection,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _find_best_overlay(self, model_id: str) -> dict | None:
        """Find the best-matching overlay for *model_id*.

        Uses ``fnmatch`` for glob-style pattern matching against the model
        ID.  When multiple patterns match, the longest (most specific)
        pattern wins.
        """
        candidates: list[tuple[int, dict]] = []

        for pattern, data in self._overlays.items():
            if fnmatch.fnmatch(model_id, pattern):
                candidates.append((len(pattern), data))

        if not candidates:
            return None

        # Most specific (longest pattern) wins
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
