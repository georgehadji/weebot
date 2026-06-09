"""SkillVariantStorePort — abstract port for skill variant persistence.

Implements the Dependency Inversion Principle: Application layer defines
the contract, Infrastructure layer provides the SQLite adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from weebot.domain.models.skill_variant import SkillVariant


class SkillVariantStorePort(ABC):
    """Abstract port for storing and querying skill variants."""

    @abstractmethod
    async def insert(self, variant: SkillVariant) -> str:
        """Persist a variant and return its variant_id."""

    @abstractmethod
    async def get_by_domain(
        self, domain: str, limit: int = 50
    ) -> list[SkillVariant]:
        """Return all variants for a domain, ordered by score descending."""

    @abstractmethod
    async def get_by_id(
        self, variant_id: str
    ) -> Optional[SkillVariant]:
        """Return a single variant by ID."""

    @abstractmethod
    async def update_score(self, variant_id: str, score: float) -> None:
        """Update the evaluation score for a variant."""

    @abstractmethod
    async def increment_children(self, variant_id: str) -> None:
        """Increment the children_count for a parent variant."""

    @abstractmethod
    async def get_parent_candidates(
        self, domain: str, top_k: int = 10
    ) -> list[SkillVariant]:
        """Return top variants for parent selection in a domain."""
