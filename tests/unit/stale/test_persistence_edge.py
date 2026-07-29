"""Edge-case tests for persistence adapters from HyperAgents implementation."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from weebot.infrastructure.persistence.skill_variant_store import SkillVariantStore
from weebot.infrastructure.persistence.strategy_store import StrategyStore
from weebot.infrastructure.persistence.meta_improvement_log import MetaImprovementLog
from weebot.domain.models.skill_variant import SkillVariant
from weebot.domain.models.self_improvement import ImprovementStrategy


class TestSkillVariantStoreEdgeCases:
    """Edge cases for the SkillVariant SQLite store."""

    @pytest.fixture
    def temp_db(self) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "test_variants.db"
        yield path
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def store(self, temp_db: Path) -> SkillVariantStore:
        return SkillVariantStore(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_empty_domain_returns_empty(self, store: SkillVariantStore) -> None:
        result = await store.get_by_domain("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_insert_and_retrieve_by_id(self, store: SkillVariantStore) -> None:
        v = SkillVariant(
            variant_id="test-1", domain="coding", score=0.9,
            skill_content="print('hello')", content_hash="sha",
        )
        await store.insert(v)
        retrieved = await store.get_by_id("test-1")
        assert retrieved is not None
        assert retrieved.domain == "coding"
        assert retrieved.score == 0.9

    @pytest.mark.asyncio
    async def test_update_score(self, store: SkillVariantStore) -> None:
        v = SkillVariant(variant_id="s1", domain="coding", score=0.5)
        await store.insert(v)
        await store.update_score("s1", 0.95)
        retrieved = await store.get_by_id("s1")
        assert retrieved.score == 0.95

    @pytest.mark.asyncio
    async def test_increment_children(self, store: SkillVariantStore) -> None:
        v = SkillVariant(variant_id="p1", domain="coding", children_count=0)
        await store.insert(v)
        await store.increment_children("p1")
        await store.increment_children("p1")
        retrieved = await store.get_by_id("p1")
        assert retrieved.children_count == 2

    @pytest.mark.asyncio
    async def test_get_by_domain_ordered_by_score(self, store: SkillVariantStore) -> None:
        await store.insert(SkillVariant(variant_id="a", domain="coding", score=0.3))
        await store.insert(SkillVariant(variant_id="b", domain="coding", score=0.9))
        await store.insert(SkillVariant(variant_id="c", domain="coding", score=0.6))

        result = await store.get_by_domain("coding")
        assert result[0].variant_id == "b"  # 0.9
        assert result[1].variant_id == "c"  # 0.6
        assert result[2].variant_id == "a"  # 0.3


class TestStrategyStoreEdgeCases:
    """Edge cases for the StrategyStore SQLite adapter."""

    @pytest.fixture
    def temp_db(self) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "test_strategies.db"
        yield path
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def store(self, temp_db: Path) -> StrategyStore:
        return StrategyStore(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_no_strategies_for_empty_db(self, store: StrategyStore) -> None:
        result = await store.get_for_domain("math")
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_out_same_domain(self, store: StrategyStore) -> None:
        await store.insert(ImprovementStrategy(
            source_domain="math", meta_agent_prompt_snippet="Math strategy",
            effectiveness_score=0.9,
        ))
        await store.insert(ImprovementStrategy(
            source_domain="coding", meta_agent_prompt_snippet="Coding strategy",
            effectiveness_score=0.8,
        ))
        result = await store.get_for_domain("math")
        # Should only get coding strategy, not math (same domain filtered)
        assert len(result) == 1
        assert result[0].source_domain == "coding"

    @pytest.mark.asyncio
    async def test_respects_min_score(self, store: StrategyStore) -> None:
        await store.insert(ImprovementStrategy(
            source_domain="coding", meta_agent_prompt_snippet="Good",
            effectiveness_score=0.9,
        ))
        await store.insert(ImprovementStrategy(
            source_domain="coding", meta_agent_prompt_snippet="Bad",
            effectiveness_score=0.3,
        ))
        result = await store.get_for_domain("math", min_score=0.7)
        assert len(result) == 1
        assert result[0].meta_agent_prompt_snippet == "Good"

    @pytest.mark.asyncio
    async def test_increment_transfer_count(self, store: StrategyStore) -> None:
        s = ImprovementStrategy(
            source_domain="coding", meta_agent_prompt_snippet="Test",
            effectiveness_score=0.9,
        )
        sid = await store.insert(s)
        await store.increment_transfer(sid)
        await store.increment_transfer(sid)
        retrieved = await store.get_by_id(sid)
        assert retrieved.transfer_count == 2


class TestMetaImprovementLogEdgeCases:
    """Edge cases for MetaImprovementLog."""

    @pytest.fixture
    def temp_db(self) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "test_meta_log.db"
        yield path
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.fixture
    def log(self, temp_db: Path) -> MetaImprovementLog:
        return MetaImprovementLog(db_path=temp_db)

    @pytest.mark.asyncio
    async def test_empty_log_returns_empty(self, log: MetaImprovementLog) -> None:
        recent = await log.get_recent()
        assert recent == []

    @pytest.mark.asyncio
    async def test_record_with_all_none_optionals(self, log: MetaImprovementLog) -> None:
        edit_id = await log.record(
            editor="Test", target_file="test.py",
            change_summary="Minimal change",
        )
        assert edit_id
        recent = await log.get_recent()
        assert len(recent) == 1
        assert recent[0]["previous_hash"] is None

    @pytest.mark.asyncio
    async def test_get_recent_respects_limit(self, log: MetaImprovementLog) -> None:
        for i in range(10):
            await log.record("Test", "test.py", f"Change {i}")
        recent = await log.get_recent(limit=3)
        assert len(recent) == 3

    @pytest.mark.asyncio
    async def test_edit_ids_are_unique(self, log: MetaImprovementLog) -> None:
        ids = set()
        for _ in range(5):
            eid = await log.record("Test", "test.py", "Change")
            assert eid not in ids
            ids.add(eid)
