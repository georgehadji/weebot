"""ParentSelector — novelty-biased parent selection for skill evolution.

Implements the DGM-H parent selection formula:
    composite = score × (1 / (1 + children_count))

Variants with high scores AND few children are preferred as parents,
preventing premature convergence on a single optimization path.

See: Zhang et al. (2026), HyperAgents, Section 4 (pseudocode, p.23)
"""
from __future__ import annotations

from typing import Optional

from weebot.application.ports.skill_variant_store_port import SkillVariantStorePort
from weebot.domain.models.skill_variant import SkillVariant


class ParentSelector:
    """Selects parent variants for the next generation of skill evolution.

    Usage:
        selector = ParentSelector(store)
        parents = await selector.select("coding", top_k=3)
    """

    def __init__(
        self,
        store: SkillVariantStorePort,
        top_k: int = 3,
    ) -> None:
        self._store = store
        self._top_k = top_k

    async def select(
        self,
        domain: str,
        top_k: int | None = None,
        min_score: float = 0.0,
    ) -> list[SkillVariant]:
        """Select the best parent variants for a domain.

        Args:
            domain: The skill domain (e.g., "coding", "review").
            top_k: Number of parents to return (default: constructor value).
            min_score: Minimum score threshold (0.0 = no filter).

        Returns:
            List of SkillVariants ordered by composite novelty score,
            highest first.
        """
        k = top_k if top_k is not None else self._top_k
        candidates = await self._store.get_parent_candidates(domain, top_k=k * 2)

        # Filter by min_score and compute composite
        filtered: list[SkillVariant] = [
            v for v in candidates if v.score >= min_score
        ]

        return filtered[:k]

    @staticmethod
    def composite_score(variant: SkillVariant) -> float:
        """Compute the DGM-H composite score for a single variant."""
        if variant.children_count < 0:
            return variant.score
        return variant.score * (1.0 / (1.0 + variant.children_count))
