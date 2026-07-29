"""Tests for SkillVariant domain model, store, and ParentSelector."""
from __future__ import annotations

import pytest
from weebot.domain.models.skill_variant import SkillVariant
from weebot.application.services.parent_selector import ParentSelector


class TestSkillVariant:
    """Tests for the SkillVariant domain model."""

    def test_default_values(self) -> None:
        v = SkillVariant()
        assert v.variant_id == ""
        assert v.parent_id is None
        assert v.score == 0.0
        assert v.children_count == 0
        assert v.generation == 0

    def test_create_with_fields(self) -> None:
        v = SkillVariant(
            variant_id="abc-123",
            parent_id="parent-456",
            skill_name="test_skill",
            skill_content="print('hello')",
            content_hash="sha256...",
            score=0.85,
            domain="coding",
            generation=2,
            children_count=3,
            meta_notes="Improved error handling",
        )
        assert v.variant_id == "abc-123"
        assert v.score == 0.85
        assert v.domain == "coding"
        assert v.children_count == 3


class MockSkillVariantStore:
    """In-memory mock for testing ParentSelector without SQLite."""

    def __init__(self, variants: list[SkillVariant] | None = None) -> None:
        self._variants: dict[str, SkillVariant] = {}
        if variants:
            for v in variants:
                self._variants[v.variant_id] = v

    async def get_parent_candidates(
        self, domain: str, top_k: int = 10
    ) -> list[SkillVariant]:
        # Return variants sorted by composite score (matching real store)
        domain_variants = [
            v for v in self._variants.values() if v.domain == domain
        ]
        return sorted(
            domain_variants,
            key=lambda v: ParentSelector.composite_score(v),
            reverse=True,
        )[:top_k]

    async def insert(self, variant: SkillVariant) -> str:
        self._variants[variant.variant_id] = variant
        return variant.variant_id

    async def update_score(self, variant_id: str, score: float) -> None:
        if variant_id in self._variants:
            self._variants[variant_id].score = score

    async def increment_children(self, variant_id: str) -> None:
        if variant_id in self._variants:
            self._variants[variant_id].children_count += 1


class TestParentSelector:
    """Tests for novelty-biased parent selection."""

    def _make_variant(
        self, vid: str, score: float, children: int, domain: str = "coding"
    ) -> SkillVariant:
        return SkillVariant(
            variant_id=vid, score=score, children_count=children,
            domain=domain, skill_content="test",
        )

    def test_composite_score_formula(self) -> None:
        """Verify the DGM-H formula: score × (1 / (1 + children_count))."""
        v = self._make_variant("a", score=0.8, children=0)
        assert ParentSelector.composite_score(v) == 0.8  # 0.8 * (1/1)

        v2 = self._make_variant("b", score=0.8, children=3)
        assert ParentSelector.composite_score(v2) == 0.2  # 0.8 * (1/4)

        v3 = self._make_variant("c", score=1.0, children=9)
        assert ParentSelector.composite_score(v3) == 0.1  # 1.0 * (1/10)

    @pytest.mark.asyncio
    async def test_prefers_high_score_low_children(self) -> None:
        """Variants with higher scores and fewer children should rank higher."""
        variants = [
            self._make_variant("a", score=0.9, children=9),  # composite: 0.09
            self._make_variant("b", score=0.7, children=0),  # composite: 0.70
            self._make_variant("c", score=0.8, children=1),  # composite: 0.40
        ]
        store = MockSkillVariantStore(variants)
        selector = ParentSelector(store, top_k=3)

        result = await selector.select("coding")
        # b (0.70) > c (0.40) > a (0.09)
        assert result[0].variant_id == "b"
        assert result[1].variant_id == "c"
        assert result[2].variant_id == "a"

    @pytest.mark.asyncio
    async def test_filters_by_min_score(self) -> None:
        """Variants below min_score should be excluded."""
        variants = [
            self._make_variant("a", score=0.9, children=0),
            self._make_variant("b", score=0.1, children=0),  # below threshold
        ]
        store = MockSkillVariantStore(variants)
        selector = ParentSelector(store, top_k=3)

        result = await selector.select("coding", min_score=0.5)
        assert len(result) == 1
        assert result[0].variant_id == "a"

    @pytest.mark.asyncio
    async def test_respects_top_k(self) -> None:
        variants = [
            self._make_variant(f"v{i}", score=0.5, children=0)
            for i in range(10)
        ]
        store = MockSkillVariantStore(variants)
        selector = ParentSelector(store, top_k=3)

        result = await selector.select("coding")
        assert len(result) == 3
