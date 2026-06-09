"""PromptRegistry — versioned prompt store and resolver.

Implements Enhancement 5 from the HyperAgents plan: agent prompts are
versioned, editable artifacts stored alongside skill variants.  The
registry manages the active variant per agent type and supports the
SelfImprover's prompt-editing capability.

Prompts are stored as text files under config/prompts/variants/ with
UUID filenames.  The in-memory registry maps variant_id → content
and tracks which variant is active for each agent type.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from weebot.domain.models.prompt_variant import PromptVariant, PromptVariantSource

logger = logging.getLogger(__name__)

# Default prompt directory relative to weebot package
_PROMPT_VARIANTS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "prompts" / "variants"


class PromptRegistry:
    """Versioned prompt store.

    Usage:
        registry = PromptRegistry()
        vid = registry.create(parent_id=None, content="...", agent_type="executor")
        registry.set_active("executor", vid)
        prompt = registry.get("executor")  # returns active variant content
    """

    def __init__(self, variants_dir: Path | None = None) -> None:
        self._dir = variants_dir or _PROMPT_VARIANTS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        # In-memory index: agent_type → active variant_id
        self._active: dict[str, str] = {}
        # In-memory cache: variant_id → PromptVariant
        self._cache: dict[str, PromptVariant] = {}

    def create(
        self,
        parent_id: str | None,
        content: str,
        agent_type: str,
        source: PromptVariantSource = PromptVariantSource.HUMAN,
    ) -> str:
        """Create a new prompt variant and persist it to disk.

        Args:
            parent_id: ID of the parent variant (None for seed).
            content: The full prompt text.
            agent_type: "executor", "planner", or "meta_critic".
            source: Who created this variant.

        Returns:
            The new variant_id (UUID).
        """
        vid = str(uuid.uuid4())
        variant = PromptVariant(
            variant_id=vid,
            parent_id=parent_id,
            agent_type=agent_type,
            prompt_content=content,
            source=source,
            is_active=False,
        )

        # Persist to disk
        file_path = self._dir / f"{vid}.txt"
        file_path.write_text(content, encoding="utf-8")

        # Cache in memory
        self._cache[vid] = variant
        logger.info(
            "Created prompt variant %s for %s (source: %s, %d chars)",
            vid, agent_type, source.value, len(content),
        )
        return vid

    def get(self, agent_type: str) -> str | None:
        """Return the active prompt content for *agent_type*, or None."""
        vid = self._active.get(agent_type)
        if vid is None:
            # Try loading active marker from disk
            marker_path = self._dir / f".active_{agent_type}"
            try:
                if marker_path.exists():
                    vid = marker_path.read_text().strip()
                    self._active[agent_type] = vid
                else:
                    return None
            except Exception:
                return None
        if vid is None:
            return None
        variant = self._cache.get(vid)
        if variant is not None:
            return variant.prompt_content
        # Try loading from disk
        return self._load_from_disk(vid)

    def get_variant(self, variant_id: str) -> PromptVariant | None:
        """Return variant metadata by ID."""
        if variant_id in self._cache:
            return self._cache[variant_id]
        content = self._load_from_disk(variant_id)
        if content is None:
            return None
        return PromptVariant(
            variant_id=variant_id,
            agent_type="unknown",
            prompt_content=content,
        )

    def set_active(self, agent_type: str, variant_id: str) -> None:
        """Set the active variant for an agent type.

        Persists the active marker to disk so other registry instances
        pointing at the same directory can resolve the active variant.
        """
        self._active[agent_type] = variant_id
        if variant_id in self._cache:
            self._cache[variant_id].is_active = True
        # Persist active marker to disk
        marker_path = self._dir / f".active_{agent_type}"
        marker_path.write_text(variant_id)
        logger.info("Set active prompt for %s → %s", agent_type, variant_id)

    def list_variants(self, agent_type: str | None = None) -> list[PromptVariant]:
        """List all known variants, optionally filtered by agent_type."""
        result = list(self._cache.values())
        if agent_type:
            result = [v for v in result if v.agent_type == agent_type]
        return sorted(result, key=lambda v: v.created_at, reverse=True)

    def _load_from_disk(self, variant_id: str) -> str | None:
        """Load prompt content from disk by variant_id."""
        file_path = self._dir / f"{variant_id}.txt"
        try:
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to load prompt variant %s: %s", variant_id, exc)
        return None
