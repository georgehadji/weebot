"""A short call to a reasoning model leaves room for its answer.

On OpenRouter `max_tokens` covers reasoning and visible output together. Found
on the 2026-10-23 smoke run after the role table moved to reasoning models:
the self-critique scorer (`max_tokens=100`) got truncated JSON and trajectory
analysis (`max_tokens=500`) an empty reply -- the budget went to reasoning.
A GLM-only workaround existed; the catalog now drives it for every model:
a short call that names no effort runs at the model's lowest effort, and a
model that cannot stop reasoning gets headroom on top of the caller's budget.
"""

from __future__ import annotations

from weebot.infrastructure.adapters.llm.openai_adapter import (
    SHORT_CALL_TOKENS,
    OpenAIAdapter,
)


def _kwargs(model: str, **kw) -> dict:
    adapter = OpenAIAdapter(api_key="sk-or-v1-test", default_model=model)
    return adapter._build_kwargs(messages=[{"role": "user", "content": "hi"}], model=model, **kw)


def test_a_short_call_turns_optional_reasoning_off():
    kw = _kwargs("openai/gpt-6-luna", max_tokens=100)
    assert kw["reasoning_effort"] == "none"
    assert kw["max_tokens"] == 100


def test_a_mandatory_reasoner_gets_low_effort_and_headroom():
    kw = _kwargs("openai/gpt-6.1-sol", max_tokens=500)
    assert kw["reasoning_effort"] == "low"
    assert kw["max_tokens"] == 500 + SHORT_CALL_TOKENS


def test_a_long_call_is_left_alone():
    kw = _kwargs("openai/gpt-6.1-sol", max_tokens=4096)
    assert "reasoning_effort" not in kw
    assert kw["max_tokens"] == 4096


def test_an_explicit_effort_wins():
    kw = _kwargs("openai/gpt-6-luna", max_tokens=100, reasoning_effort="high")
    assert kw["reasoning_effort"] == "high"
