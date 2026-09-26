"""OpenAIAdapter sends the parameters the catalog says a model accepts.

Name heuristics decided this before: any id containing "gpt" lost its
temperature (gpt-4.1 accepts one), everything else kept it (Claude Sonnet 5
does not list it), and every `:thinking` model was asked for effort "max" --
which z-ai/glm-5.2, the planner and executor tier 1, does not accept.
"""

from __future__ import annotations

from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter, _fit_effort
from weebot.domain.models.model_config import ModelConfig, ModelTier


def _kwargs(model: str, **kw) -> dict:
    adapter = OpenAIAdapter(api_key="sk-or-v1-test", default_model=model)
    return adapter._build_kwargs(messages=[{"role": "user", "content": "hi"}], model=model, **kw)


def test_temperature_follows_the_catalog_not_the_name():
    assert _kwargs("openai/gpt-4.1-nano", temperature=0.2).get("temperature") == 0.2
    assert "temperature" not in _kwargs("anthropic/claude-sonnet-5", temperature=0.2)


def test_an_unknown_model_keeps_the_name_heuristic():
    assert "temperature" not in _kwargs("gpt-bare-direct-id", temperature=0.2)
    assert _kwargs("some-direct-model", temperature=0.2).get("temperature") == 0.2


def test_thinking_default_effort_is_fitted_to_the_model():
    assert _kwargs("z-ai/glm-5.2:thinking")["reasoning_effort"] == "xhigh"


def _spec(efforts, mandatory=False) -> ModelConfig:
    return ModelConfig(
        name="m", provider="openrouter", cost_per_1k_tokens=0.0, context_window=1,
        strengths=[], tier=ModelTier.FAST, api_key_env="K",
        reasoning_efforts=efforts, reasoning_mandatory=mandatory,
    )


def test_fit_effort_steps_down_and_never_offers_none_to_a_mandatory_model():
    assert _fit_effort("max", _spec(["xhigh", "high"])) == "xhigh"
    assert _fit_effort("medium", _spec(["high", "low"])) == "low"
    assert _fit_effort("minimal", _spec(["high", "medium"])) == "medium"  # nothing lower
    assert _fit_effort("none", _spec(["high", "low", "none"], mandatory=True)) == "low"
    assert _fit_effort("high", _spec(["high", "low"])) == "high"
    assert _fit_effort("max", None) == "max"  # unknown model: unchanged
