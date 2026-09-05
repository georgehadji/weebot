"""Wave 5 of the V7 defect hunt — cascade accounting and model selection.

Cost-accounting defects are silent by construction: the symptom is a number
that reads 0.0. These tests assert on the accounting, not on the call
succeeding.

* ``getattr(resp, "usage", {}).get(...) if hasattr(resp, "usage") else 0``
  guarded nothing. ``usage`` is a declared field, so ``hasattr`` is always
  True, and four adapters set it to ``None`` when a provider omits it -- so the
  success path raised ``AttributeError`` on the accounting line. The adapters
  themselves already use the correct ``getattr(response, "usage", None)``
  truthiness form.
* No ``_record_decision`` caller ever passed ``cost_estimate``, so the tracker's
  ``total_cost_estimate`` was structurally 0.0 -- and ``mcp/resources.py:297``
  publishes that number as cost accounting. ``estimate_cost()`` existed and was
  never called.
* ``_check_openrouter_credits`` returned 0 on API error, commented "fail open".
  0 >= threshold is false, so a transient network error to openrouter.ai
  silently stripped every OpenRouter-only model from the cascade.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.core.model_cascade_tracker import ModelCascadeTracker
from weebot.domain.models.llm_response import LLMResponse


def _executor(response: LLMResponse, tracker: ModelCascadeTracker) -> CascadeExecutor:
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=response)
    return CascadeExecutor(llm=llm, tools=MagicMock(), tracker=tracker)


class TestTokenAccountingSurvivesMissingUsage:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "usage", [None, {}, {"total_tokens": 42}], ids=["none", "empty", "populated"]
    )
    async def test_success_path_does_not_raise(self, usage):
        tracker = ModelCascadeTracker()
        resp = LLMResponse(content="hello")
        resp.usage = usage

        out = await _executor(resp, tracker)._cascade_try_chat(
            messages=[{"role": "user", "content": "hi"}], model_id="openai/gpt-4"
        )

        assert out is not None
        assert out.content == "hello"

    @pytest.mark.asyncio
    async def test_token_count_is_recorded_when_usage_is_present(self):
        tracker = ModelCascadeTracker()
        resp = LLMResponse(content="hello")
        resp.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

        await _executor(resp, tracker)._cascade_try_chat(
            messages=[{"role": "user", "content": "hi"}], model_id="openai/gpt-4"
        )

        assert tracker.recent(1)[0].token_count == 15

    @pytest.mark.asyncio
    async def test_token_count_is_zero_not_an_error_when_usage_is_none(self):
        tracker = ModelCascadeTracker()
        resp = LLMResponse(content="hello")
        resp.usage = None

        await _executor(resp, tracker)._cascade_try_chat(
            messages=[{"role": "user", "content": "hi"}], model_id="openai/gpt-4"
        )

        assert tracker.recent(1)[0].token_count == 0


class TestCostIsActuallyEstimated:
    @pytest.mark.asyncio
    async def test_a_priced_model_reports_a_non_zero_cost(self):
        """The whole point: total_cost_estimate must stop being structurally 0.0."""
        tracker = ModelCascadeTracker()
        resp = LLMResponse(content="hello")
        resp.usage = {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000}

        await _executor(resp, tracker)._cascade_try_chat(
            messages=[{"role": "user", "content": "hi"}],
            model_id="x-ai/grok-build-0.1",  # priced in MODEL_CASCADE
        )

        summary = tracker.summary()
        assert summary["total_cost_estimate"] > 0.0, (
            f"cost still reads {summary['total_cost_estimate']} — "
            "mcp/resources.py publishes this as cost accounting"
        )

    @pytest.mark.asyncio
    async def test_an_unpriced_model_reports_zero_without_erroring(self):
        """Boundary, and a real limit: estimate_cost() only knows models listed
        in MODEL_CASCADE (9 priced ids at time of writing) and returns 0.0 for
        anything else. Cost accounting is therefore complete only for that set --
        recorded as residual risk in the W5 audit, not fixed here."""
        tracker = ModelCascadeTracker()
        resp = LLMResponse(content="hello")
        resp.usage = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}

        await _executor(resp, tracker)._cascade_try_chat(
            messages=[{"role": "user", "content": "hi"}],
            model_id="some/unknown-model-with-no-price",
        )

        assert tracker.summary()["total_cost_estimate"] >= 0.0


class TestCreditCheckFailsOpen:
    @pytest.mark.asyncio
    async def test_unknown_credits_do_not_filter_models(self, monkeypatch):
        async def unavailable():
            return None  # what the except branch now returns

        monkeypatch.setattr(
            CascadeExecutor, "_check_openrouter_credits", staticmethod(unavailable)
        )
        monkeypatch.setattr(CascadeExecutor, "_get_credit_threshold", staticmethod(lambda: 10000))

        models = ["openai/gpt-4", "anthropic/claude-3", "deepseek/chat"]
        assert await CascadeExecutor.get_credits_and_filter_direct(models) == models

    @pytest.mark.asyncio
    async def test_genuinely_low_credits_still_filter(self, monkeypatch):
        """No-regression: a real low-credit reading must still skip OpenRouter models."""

        async def low():
            return 5

        monkeypatch.setattr(CascadeExecutor, "_check_openrouter_credits", staticmethod(low))
        monkeypatch.setattr(CascadeExecutor, "_get_credit_threshold", staticmethod(lambda: 10000))

        models = ["openai/gpt-4", "anthropic/claude-3", "deepseek/chat"]
        kept = await CascadeExecutor.get_credits_and_filter_direct(models)

        assert kept == ["deepseek/chat"]

    @pytest.mark.asyncio
    async def test_ample_credits_keep_everything(self, monkeypatch):
        async def plenty():
            return 999_999

        monkeypatch.setattr(CascadeExecutor, "_check_openrouter_credits", staticmethod(plenty))
        monkeypatch.setattr(CascadeExecutor, "_get_credit_threshold", staticmethod(lambda: 10000))

        models = ["openai/gpt-4", "deepseek/chat"]
        assert await CascadeExecutor.get_credits_and_filter_direct(models) == models


class TestAdapterCacheLookupCanHit:
    def test_get_adapter_finds_what_create_adapter_cached(self):
        """The read key had three parts against the write key's four."""
        from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory

        factory = AdapterFactory()
        sentinel = object()
        factory._adapters["openai:gpt-4:sk-abc123:caching"] = sentinel

        assert factory.get_adapter("openai", "gpt-4") is sentinel

    def test_get_adapter_returns_none_for_an_uncached_model(self):
        from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory

        factory = AdapterFactory()
        factory._adapters["openai:gpt-4:sk-abc123:caching"] = object()

        assert factory.get_adapter("openai", "gpt-5") is None
        assert factory.get_adapter("anthropic", "gpt-4") is None
