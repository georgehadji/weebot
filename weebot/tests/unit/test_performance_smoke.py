"""Performance smoke tests for HyperAgents archive stores.

All tests are time-bounded to prevent CI flakiness.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from weebot.application.services.parent_selector import ParentSelector
from weebot.domain.models.skill_variant import SkillVariant


class TestParentSelectorPerformance:
    """Smoke tests for ParentSelector with realistic variant counts."""

    @pytest.fixture
    def large_archive(self) -> list[SkillVariant]:
        """Create 500 variants across 3 domains."""
        variants = []
        for i in range(500):
            domain = ["coding", "review", "math"][i % 3]
            variants.append(
                SkillVariant(
                    variant_id=f"v{i}", domain=domain,
                    score=(i % 100) / 100.0,
                    children_count=i % 10,
                    skill_content=f"content-{i}",
                    content_hash=f"hash-{i}",
                )
            )
        return variants

    @pytest.mark.asyncio
    async def test_select_with_500_variants(self, large_archive: list[SkillVariant]) -> None:
        """ParentSelector.select() should complete in < 50ms with 500 variants."""
        from weebot.tests.unit.test_skill_variant import MockSkillVariantStore

        store = MockSkillVariantStore(large_archive)
        selector = ParentSelector(store, top_k=5)

        start = time.perf_counter()
        result = await selector.select("coding")
        elapsed = time.perf_counter() - start

        assert len(result) <= 5
        assert elapsed < 0.05, f"select took {elapsed:.3f}s"


class TestPromptRegistryPerformance:
    """Smoke tests for PromptRegistry with many variants."""

    @pytest.fixture
    def tmp_dir(self) -> Path:
        d = tempfile.mkdtemp()
        yield Path(d)
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_create_100_variants(self, tmp_dir: Path) -> None:
        """Creating 100 variants should complete quickly."""
        from weebot.application.services.prompt_registry import PromptRegistry

        registry = PromptRegistry(variants_dir=tmp_dir)
        start = time.perf_counter()
        for i in range(100):
            registry.create(
                parent_id=None,
                content=f"Prompt variant {i} content",
                agent_type="executor",
            )
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"100 creates took {elapsed:.3f}s"

        # Verify all were created
        variants = registry.list_variants()
        assert len(variants) == 100


class TestMetaImprovementLogPerformance:
    """Smoke tests for MetaImprovementLog with many entries."""

    @pytest.fixture
    def temp_db(self) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "perf_log.db"
        yield path
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_append_100_entries(self, temp_db: Path) -> None:
        """Appending 100 entries should complete in < 2s."""
        from weebot.infrastructure.persistence.meta_improvement_log import (
            MetaImprovementLog,
        )

        log = MetaImprovementLog(db_path=temp_db)
        start = time.perf_counter()
        for i in range(100):
            await log.record("Test", "test.py", f"Change {i}")
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"100 appends took {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_get_recent_after_many_entries(self, temp_db: Path) -> None:
        """get_recent should be fast even with many entries."""
        from weebot.infrastructure.persistence.meta_improvement_log import (
            MetaImprovementLog,
        )

        log = MetaImprovementLog(db_path=temp_db)
        for i in range(200):
            await log.record("Test", "test.py", f"Change {i}")

        start = time.perf_counter()
        recent = await log.get_recent(limit=20)
        elapsed = time.perf_counter() - start

        assert len(recent) == 20
        assert elapsed < 0.1, f"get_recent took {elapsed:.3f}s"


class TestStrategyStorePerformance:
    """Smoke tests for StrategyStore queries."""

    @pytest.fixture
    def temp_db(self) -> Path:
        d = tempfile.mkdtemp()
        path = Path(d) / "perf_strategies.db"
        yield path
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_query_with_many_strategies(self, temp_db: Path) -> None:
        """get_for_domain should complete in < 50ms with 100 strategies."""
        from weebot.infrastructure.persistence.strategy_store import StrategyStore
        from weebot.domain.models.self_improvement import ImprovementStrategy

        store = StrategyStore(db_path=temp_db)
        domains = ["coding", "review", "robotics", "math"]

        for i in range(100):
            await store.insert(ImprovementStrategy(
                source_domain=domains[i % 4],
                meta_agent_prompt_snippet=f"Strategy {i}",
                effectiveness_score=(i % 100) / 100.0,
            ))

        start = time.perf_counter()
        result = await store.get_for_domain("math")
        elapsed = time.perf_counter() - start

        # Should only return strategies from non-math domains
        for s in result:
            assert s.source_domain != "math"
        assert elapsed < 0.1, f"get_for_domain took {elapsed:.3f}s"
