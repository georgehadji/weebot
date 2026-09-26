"""Proof tests for ModelConfig's field validation and the selection clamps.

The catalog generator learned to reject a negative ``cost_per_1k_tokens``, but
the generator is only one of several places model definitions are written in
this repo, and it is not the one the application reads at runtime. These tests
pin the guard at the seam every consumer passes through instead.

The defect being guarded: ``_strategies.py`` *subtracts* cost from a score, so a
negative cost adds score without bound, and the budget filter ``cost <= budget``
admits it at any budget including zero. A catalog carrying four entries priced
at ``-1000.0`` made every cost- and speed-based selection return the same
meta-router regardless of task or budget.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.model_config import ModelConfig, ModelTier
from weebot.application.services.model_registry._strategies import (
    CostOptimized,
    Fastest,
    QualityOptimized,
)
from weebot.domain.models.task_type import TaskType


def _config(**overrides) -> ModelConfig:
    base = dict(
        name="test-model",
        provider="openrouter",
        cost_per_1k_tokens=0.001,
        context_window=128_000,
        strengths=[TaskType.CHAT],
        tier=ModelTier.STANDARD,
        api_key_env="OPENROUTER_API_KEY",
    )
    base.update(overrides)
    return ModelConfig(**base)


def test_a_negative_cost_cannot_be_constructed():
    with pytest.raises(ValueError, match="must not be negative"):
        _config(cost_per_1k_tokens=-1000.0)


def test_a_zero_cost_is_allowed():
    """Free models are real; only a negative rate is nonsense."""
    assert _config(cost_per_1k_tokens=0.0).cost_per_1k_tokens == 0.0


@pytest.mark.parametrize("bad", [None, 0, -1, "128000"])
def test_a_context_window_that_is_not_a_positive_int_cannot_be_constructed(bad):
    """`context_window=None` used to render, import cleanly, and then raise
    TypeError inside QualityOptimized on every single selection."""
    with pytest.raises(ValueError, match="context_window"):
        _config(context_window=bad)


def _mutated_negative() -> ModelConfig:
    """A dataclass is mutable, so __post_init__ guards construction only."""
    cfg = _config(cost_per_1k_tokens=0.001, context_window=2_000_000, tier=ModelTier.FAST)
    cfg.cost_per_1k_tokens = -1000.0
    return cfg


# QualityOptimized is absent here on purpose: it does not use cost in its score
# at all (task match, tier, context window), so it has nothing to clamp. Cost
# reaches it only through the budget filter, which the next test covers.
@pytest.mark.parametrize("strategy", [CostOptimized(), Fastest()])
def test_a_mutated_negative_cost_cannot_win_scoring(strategy):
    candidates = [
        ("good/cheap", _config(cost_per_1k_tokens=0.0, tier=ModelTier.FAST)),
        ("good/paid", _config(cost_per_1k_tokens=0.01)),
        ("evil/negative", _mutated_negative()),
    ]
    assert strategy.select(candidates, TaskType.CHAT) != "evil/negative"


@pytest.mark.parametrize("strategy", [CostOptimized(), Fastest(), QualityOptimized()])
def test_a_mutated_negative_cost_does_not_pass_a_zero_budget(strategy):
    """`-1000.0 <= 0.0` is true, so no budget could exclude it."""
    candidates = [
        ("good/free", _config(cost_per_1k_tokens=0.0, tier=ModelTier.FAST)),
        ("evil/negative", _mutated_negative()),
    ]
    assert strategy.select(candidates, TaskType.CHAT, budget=0.0) == "good/free"


def test_the_budget_filter_still_admits_free_models():
    """The clamp must not turn `0 <= cost <= budget` into an off-by-one."""
    candidates = [("good/free", _config(cost_per_1k_tokens=0.0))]
    assert CostOptimized().select(candidates, TaskType.CHAT, budget=0.0) == "good/free"


def test_the_budget_filter_still_excludes_a_model_over_budget():
    with pytest.raises(ValueError, match="budget"):
        CostOptimized().select([("x/pricey", _config(cost_per_1k_tokens=5.0))], TaskType.CHAT, 0.1)


def test_every_shipped_model_survives_its_own_validation():
    """The catalog is constructed at import, so this is really a statement that
    importing it did not raise -- made explicit so a future hand-edit that
    reintroduces a bad value fails here by name."""
    from weebot.config.model_catalog import MODELS

    assert MODELS
    for model_id, cfg in MODELS.items():
        assert cfg.cost_per_1k_tokens >= 0, model_id
        assert isinstance(cfg.context_window, int) and cfg.context_window > 0, model_id


def _metadata_config(**kw) -> ModelConfig:
    return ModelConfig(
        name="m", provider="openrouter", cost_per_1k_tokens=0.01, context_window=1000,
        strengths=[], tier=ModelTier.STANDARD, api_key_env="K", **kw,
    )


def test_capabilities_are_unknown_until_the_catalog_says_otherwise():
    """None, not False: a hand-added model the API never described has not been
    shown to lack tools. Callers decide whether unknown passes their gate."""
    bare = _metadata_config()
    assert bare.supports_tools is None and bare.supports_vision is None
    described = _metadata_config(supported_parameters=["tools"], input_modalities=["text"])
    assert described.supports_tools is True and described.supports_vision is False
    assert described.supports_reasoning is False


def test_estimate_cost_uses_the_split_rates_when_known():
    split = _metadata_config(prompt_cost_per_1k=0.002, completion_cost_per_1k=0.01)
    assert split.estimate_cost(1000, 1000) == pytest.approx(0.012)
    # Falls back to the blended rate for both sides when the split is unknown.
    assert _metadata_config().estimate_cost(1000, 1000) == pytest.approx(0.02)
