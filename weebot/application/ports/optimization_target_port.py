"""OptimizationTarget — abstract protocol for optimizable artifacts.

Defines the interface that any optimizable target (Skill, HarnessConfig,
or future types) must implement for use with the optimization loop.

The loop calls:
  1. ``load()`` — get current version
  2. ``content`` — serialize for the optimizer LLM
  3. ``apply_edits(edits)`` — produce a new candidate
  4. ``save(candidate)`` — persist an accepted candidate
  5. ``rollback()`` — revert to last saved version
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OptimizationTarget(ABC):
    """An artifact that can be iteratively optimized.

    Type parameter T is the concrete artifact type (Skill, HarnessConfig, etc.).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identifier for the target (e.g. skill name, harness version)."""
        ...

    @property
    @abstractmethod
    def version(self) -> int:
        """Current version number (monotonically increasing)."""
        ...

    @property
    @abstractmethod
    def content(self) -> str:
        """Serialized representation for the optimizer LLM.

        This is what the optimizer sees as the "current state" — it mirrors
        ``skill.content`` for skills and a YAML snippet for harness configs.
        """
        ...

    @abstractmethod
    async def load(self) -> Any:
        """Load the current version of the target from persistent storage.

        Returns:
            The loaded artifact (Skill, HarnessConfig, etc.), or None if
            not found.
        """
        ...

    @abstractmethod
    async def apply_edits(
        self, edits: list[dict[str, Any]],
    ) -> Any:
        """Apply a set of edits to the current target, returning the candidate.

        Args:
            edits: List of edit dicts.  Schema is target-specific.

        Returns:
            The candidate artifact with edits applied.
        """
        ...

    @abstractmethod
    async def save(self, candidate: Any) -> Any:
        """Persist an accepted candidate, incrementing the version.

        Args:
            candidate: The artifact to persist.

        Returns:
            The saved artifact (with updated version/scores).
        """
        ...

    @abstractmethod
    async def rollback(self) -> Any:
        """Revert to the last saved version.

        Returns:
            The rolled-back artifact.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any resources (connections, file handles)."""
        ...
