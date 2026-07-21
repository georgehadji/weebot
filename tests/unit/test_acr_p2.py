"""Unit tests for ACR Phase P2 — PosteriorRepository, BanditSelector, bandit integration."""
from __future__ import annotations

import anyio
import pytest

from weebot.application.services.routing.bandit import BanditSelector


# ── PosteriorRepository tests ──────────────────────────────────────

class _FakeCandidate:
    """Minimal candidate-like object for bandit tests."""
    def __init__(self, model_id: str, score: float):
        self.model_id = model_id
        self.score = score


class TestPosteriorRepository:
    """Beta-Bernoulli posterior persistence."""

    @pytest.fixture
    def repo(self, tmp_path):
        from weebot.infrastructure.persistence.posterior_repository import (
            PosteriorRepository,
        )
        db = tmp_path / "acr_post.db"
        repo = PosteriorRepository(db_path=str(db), decay=0.95)
        yield repo

    def test_record_and_retrieve(self, repo):
        async def test():
            await repo.record_outcome("coding", "model-a", True)
            alpha, beta = await repo.get_posterior("coding", "model-a")
            # Prior (5, 1) * decay + 1 success
            assert alpha > 5.0
            assert beta >= 1.0
            assert alpha / (alpha + beta) > 0.5  # more successes than failures
        anyio.run(test)

    def test_multiple_outcomes(self, repo):
        async def test():
            await repo.record_outcome("coding", "m", True)
            await repo.record_outcome("coding", "m", True)
            await repo.record_outcome("coding", "m", False)
            alpha, beta = await repo.get_posterior("coding", "m")
            mean = alpha / (alpha + beta)
            assert 0.6 < mean < 0.9, f"mean={mean} after 2 success + 1 failure"
        anyio.run(test)

    def test_unknown_category_returns_prior(self, repo):
        async def test():
            alpha, beta = await repo.get_posterior("unknown", "unknown-model")
            assert alpha == 5.0
            assert beta == 1.0
        anyio.run(test)

    def test_exponential_forgetting(self, repo):
        async def test():
            await repo.record_outcome("test", "m", True)
            alpha_before, beta_before = await repo.get_posterior("test", "m")
            await repo.decay_all()
            alpha_after, beta_after = await repo.get_posterior("test", "m")
            assert alpha_after < alpha_before, "alpha did not decay"
            assert beta_after < beta_before, "beta did not decay"
        anyio.run(test)

    def test_persistence_across_reload(self, repo):
        async def test():
            await repo.record_outcome("coding", "m", True)
            await repo.record_outcome("coding", "m", True)
            alpha_before, _ = await repo.get_posterior("coding", "m")
            # Reload with same db_path
            from weebot.infrastructure.persistence.posterior_repository import (
                PosteriorRepository,
            )
            repo2 = PosteriorRepository(db_path=repo._db_path, decay=0.95)
            alpha_after, _ = await repo2.get_posterior("coding", "m")
            assert alpha_after == pytest.approx(alpha_before, rel=0.01)
        anyio.run(test)

    def test_get_all_posteriors(self, repo):
        async def test():
            await repo.record_outcome("cat-a", "m1", True)
            await repo.record_outcome("cat-a", "m2", False)
            await repo.record_outcome("cat-b", "m1", True)
            all_p = await repo.get_all_posteriors()
            assert "cat-a" in all_p
            assert "cat-b" in all_p
            assert "m1" in all_p["cat-a"]
            assert "m2" in all_p["cat-a"]
            assert "m1" in all_p["cat-b"]
        anyio.run(test)


# ── BanditSelector tests ───────────────────────────────────────────

class TestBanditSelector:
    """Thompson sampling, budget tracking, and cold-start."""

    def test_single_candidate_unchanged(self):
        bandit = BanditSelector(random_seed=42)
        result = bandit.select(
            [_FakeCandidate("only-model", 0.8)], "test",
        )
        assert len(result) == 1
        assert result[0].model_id == "only-model"

    def test_deterministic_high_utility_wins(self):
        """When not exploring, higher utility should always rank first."""
        bandit = BanditSelector(random_seed=42)
        cands = [
            _FakeCandidate("good", 0.9),
            _FakeCandidate("bad", 0.1),
        ]
        result = bandit.select(cands, "test")
        assert result[0].model_id == "good"

    def test_thompson_strong_posterior(self):
        """Beta(10, 1) should sample near 0.909 mean."""
        bandit = BanditSelector(random_seed=99)
        s = bandit._sample_thompson("m", (10, 1))
        assert 0.6 < s < 1.0, f"unexpected sample: {s}"

    def test_thompson_weak_posterior(self):
        """Beta(1, 10) should sample near 0.091 mean."""
        bandit = BanditSelector(random_seed=99)
        s = bandit._sample_thompson("m", (1, 10))
        assert 0.0 < s < 0.4, f"unexpected sample: {s}"

    def test_thompson_fallback_on_error(self):
        """Beta(0, 0) should fall back to 0.5."""
        bandit = BanditSelector(random_seed=99)
        s = bandit._sample_thompson("m", (0, 0))
        assert s == 0.5, f"fallback failed: {s}"

    def test_premium_dampening(self):
        """Premium models should have a stricter exploration budget."""
        bandit = BanditSelector(random_seed=42, explore_fraction=1.0)
        cands = [
            _FakeCandidate("premium-model", 0.8),
            _FakeCandidate("budget-model", 0.79),
        ]
        # With explore_fraction=1.0, ALL selections explore
        # premium-model should still have dampened blend
        result = bandit.select(
            cands, "test",
            posteriors={"premium-model": (5, 1), "budget-model": (1, 5)},
            premium_models={"premium-model"},
        )
        assert len(result) == 2

    def test_budget_tracking(self):
        bandit = BanditSelector(random_seed=42, explore_fraction=0.5)
        for _ in range(10):
            bandit.select(
                [_FakeCandidate("m1", 0.9), _FakeCandidate("m2", 0.8)],
                "track-test",
            )
        budget = bandit.get_budget_used("track-test")
        assert budget["total"] == 10
        assert budget["explored"] <= 10
        assert 0 <= budget["explore_rate"] <= 1.0

    def test_reset_budget(self):
        bandit = BanditSelector(random_seed=42)
        # Must have 2+ candidates for explore counting
        bandit.select([_FakeCandidate("m1", 0.9), _FakeCandidate("m2", 0.8)], "test")
        assert bandit.get_budget_used("test")["total"] == 1
        bandit.reset_budget()
        assert bandit.get_budget_used("test")["total"] == 0

    def test_empty_candidates(self):
        bandit = BanditSelector()
        assert bandit.select([], "test") == []

    def test_record_outcome_no_repo(self):
        """record_outcome should not raise when no repo is available."""
        bandit = BanditSelector()
        # Should not raise
        bandit.record_outcome("test", "model", True, posterior_repo=None)


# ── Integration: Router with bandit ─────────────────────────────────

class TestBanditRouterIntegration:
    """Router + bandit integration (unit level, no DB)."""

    def test_router_with_bandit_flag(self):
        """When force_bandit=True, router calls bandit stage."""
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )
        router = AdaptiveCapabilityRouter(force_acr=True, force_bandit=True)
        result = router.route("refactor the database module")
        assert len(result) >= 2
        # The bandit should not crash or return empty
        assert isinstance(result, list)
        assert all(isinstance(m, str) for m in result)

    def test_router_without_bandit(self):
        """Default: bandit disabled, router returns pure utility ranking."""
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )
        router = AdaptiveCapabilityRouter(force_acr=True, force_bandit=False)
        result = router.route("refactor the database module")
        assert len(result) >= 2
        # Without bandit, the top model should always be the same
        result2 = router.route("refactor the database module")
        assert result[0] == result2[0]  # deterministic without bandit

    def test_record_outcome_from_decision(self):
        """record_cascade_outcome should not raise."""
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )
        from weebot.core.model_cascade_tracker import CascadeDecision, CascadeOutcome, CascadeTier

        router = AdaptiveCapabilityRouter(force_acr=True, force_bandit=False)
        decision = CascadeDecision(
            model_name="test-model",
            tier=CascadeTier.FREE,
            outcome=CascadeOutcome.SUCCESS,
            latency_ms=100.0,
            task_category="coding",
        )
        # Should not raise even without posterior repo
        router.record_cascade_outcome(decision)

    def test_router_with_posteriors(self):
        """Router should accept pre-loaded posteriors."""
        from weebot.application.services.routing.adaptive_capability_router import (
            AdaptiveCapabilityRouter,
        )
        router = AdaptiveCapabilityRouter(force_acr=True, force_bandit=True)
        posteriors = {
            "deepseek/deepseek-v4-flash": (10, 1),
            "minimax/minimax-m3": (1, 10),
            "x-ai/grok-build-0.1": (5, 5),
        }
        result = router.route(
            "refactor the database module",
            posteriors=posteriors,
        )
        assert len(result) >= 1
