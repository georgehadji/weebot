"""Self-Improvement port — abstract interface for proposing and applying patches."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from weebot.domain.models.self_improvement import SelfImprovementPatch


class SelfImprovementPort(ABC):
    """Interface for controlled self-improvement of skills, contracts, and rules.

    Every patch goes through: propose → validate → apply (or revert).
    AST parsing + sandbox testing prevents corruption.
    """

    @abstractmethod
    async def propose_patch(
        self, context: dict[str, Any]
    ) -> Optional[SelfImprovementPatch]:
        """Propose a patch based on execution context.

        Args:
            context: Dict with session events, tool usage patterns,
                     failure modes, and current skill/config versions.

        Returns:
            A SelfImprovementPatch if a beneficial change is identified,
            None otherwise.
        """
        ...

    @abstractmethod
    async def validate_patch(self, patch: SelfImprovementPatch) -> float:
        """Validate a proposed patch by running test tasks.

        Args:
            patch: The patch to validate.

        Returns:
            Validation score 0.0–1.0.
        """
        ...

    @abstractmethod
    async def apply_patch(self, patch: SelfImprovementPatch) -> bool:
        """Apply a validated patch.

        Args:
            patch: The patch to apply.

        Returns:
            True if applied successfully, False otherwise.
        """
        ...

    @abstractmethod
    async def revert_patch(self, patch: SelfImprovementPatch) -> bool:
        """Revert a previously applied patch.

        Args:
            patch: The patch to revert.

        Returns:
            True if reverted successfully.
        """
        ...
