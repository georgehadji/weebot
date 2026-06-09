"""Tests for ImprovementStrategy and StrategyTransferService."""
from __future__ import annotations

import pytest
from weebot.domain.models.self_improvement import ImprovementStrategy
from weebot.application.services.strategy_transfer import StrategyTransferService


class TestImprovementStrategy:
    """Tests for the ImprovementStrategy domain model."""

    def test_defaults(self) -> None:
        s = ImprovementStrategy()
        assert s.strategy_id == ""
        assert s.source_domain == ""
        assert s.effectiveness_score == 0.0
        assert s.transfer_count == 0

    def test_composite_score_formula(self) -> None:
        """Transfer composite favors high-effectiveness, high-transfer strategies."""
        s = ImprovementStrategy(
            effectiveness_score=0.8,
            transfer_count=3,
        )
        assert s.composite_score == 0.8 * 4.0  # 3.2

        s2 = ImprovementStrategy(
            effectiveness_score=0.9,
            transfer_count=0,
        )
        assert s2.composite_score == 0.9 * 1.0  # 0.9


class MockStrategyStore:
    """Mock store for StrategyTransferService."""

    def __init__(self, strategies: list[ImprovementStrategy] | None = None) -> None:
        self._strategies = strategies or []

    async def get_for_domain(
        self, target_domain: str, min_score: float = 0.7, limit: int = 5
    ) -> list[ImprovementStrategy]:
        return [
            s for s in self._strategies
            if s.source_domain != target_domain
            and s.effectiveness_score >= min_score
        ][:limit]

    async def insert(self, strategy: ImprovementStrategy) -> str:
        self._strategies.append(strategy)
        return strategy.strategy_id

    async def increment_transfer(self, strategy_id: str) -> None:
        for s in self._strategies:
            if s.strategy_id == strategy_id:
                s.transfer_count += 1


class TestStrategyTransferService:
    """Tests for StrategyTransferService."""

    @pytest.fixture
    def store(self) -> MockStrategyStore:
        return MockStrategyStore([
            ImprovementStrategy(
                strategy_id="s1",
                source_domain="coding",
                meta_agent_prompt_snippet="Use web_search before browser",
                effectiveness_score=0.85,
            ),
            ImprovementStrategy(
                strategy_id="s2",
                source_domain="review",
                meta_agent_prompt_snippet="Grade step by step",
                effectiveness_score=0.9,
            ),
            ImprovementStrategy(
                strategy_id="s3",
                source_domain="math",
                meta_agent_prompt_snippet="Check solutions against rubric",
                effectiveness_score=0.5,  # below min_score
            ),
        ])

    @pytest.mark.asyncio
    async def test_get_strategies_filters_by_domain(self, store: MockStrategyStore) -> None:
        svc = StrategyTransferService(store, min_score=0.7, max_strategies=5)
        strategies = await svc.get_strategies_for("math")
        # Should get coding and review strategies, but not math (same domain)
        source_domains = {s.source_domain for s in strategies}
        assert "coding" in source_domains
        assert "review" in source_domains
        assert "math" not in source_domains

    @pytest.mark.asyncio
    async def test_get_strategies_respects_min_score(self, store: MockStrategyStore) -> None:
        svc = StrategyTransferService(store, min_score=0.8, max_strategies=5)
        strategies = await svc.get_strategies_for("math")
        # s3 (0.5) should be excluded
        scores = {s.effectiveness_score for s in strategies}
        assert 0.5 not in scores

    def test_format_for_prompt(self, store: MockStrategyStore) -> None:
        svc = StrategyTransferService(store)
        strategies = [
            ImprovementStrategy(
                source_domain="coding",
                meta_agent_prompt_snippet="Use domcontentloaded",
                effectiveness_score=0.9,
            ),
        ]
        prompt = svc.format_for_prompt(strategies)
        assert "Prior Improvement Strategies" in prompt
        assert "domcontentloaded" in prompt
        assert "coding" in prompt

    def test_format_for_prompt_empty(self, store: MockStrategyStore) -> None:
        svc = StrategyTransferService(store)
        assert svc.format_for_prompt([]) == ""
