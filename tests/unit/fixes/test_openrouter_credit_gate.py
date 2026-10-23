"""The OpenRouter credit gate reads the balance OpenRouter actually reports.

Found on the 2026-10-23 smoke run: "OpenRouter credits low (0 -- need 10000),
skipping 1 OpenRouter-only model(s)" on a key with $3.95 left. `/auth/key`
has no `credits` field -- it reports `limit` and `limit_remaining` in USD -- so
the adapter read 0 on every call, and the threshold (10000 "tokens") was in a
unit OpenRouter does not use. Every cascade dropped its OpenRouter models.
`minimax/` also counted as direct, though its adapter only reaches OpenRouter.
"""

from __future__ import annotations

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.infrastructure.adapters.llm.openrouter_account import OpenRouterAccountAdapter


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return {"data": self._data}


def _serve(monkeypatch, data):
    async def _get(self, url, headers=None):
        return _Resp(data)

    monkeypatch.setattr("httpx.AsyncClient.get", _get)


@pytest.mark.asyncio
async def test_a_limited_key_reports_its_remaining_dollars(monkeypatch):
    _serve(monkeypatch, {"limit": 10, "limit_remaining": 3.95, "usage": 6.05})
    assert await OpenRouterAccountAdapter("k").remaining_credits() == pytest.approx(3.95)


@pytest.mark.asyncio
async def test_an_unlimited_key_is_unknown_not_zero(monkeypatch):
    _serve(monkeypatch, {"limit": None, "limit_remaining": None, "usage": 1.0})
    assert await OpenRouterAccountAdapter("k").remaining_credits() is None


class _Balance:
    def __init__(self, usd):
        self._usd = usd

    async def remaining_credits(self):
        return self._usd


@pytest.mark.asyncio
async def test_a_few_dollars_keeps_openrouter_models():
    from unittest.mock import MagicMock

    ex = CascadeExecutor(llm=MagicMock(), tools=MagicMock(), provider_account=_Balance(3.95))
    models = ["openai/gpt-6.1-sol", "deepseek/deepseek-v4.1-flash"]
    assert await ex.get_credits_and_filter_direct(models) == models


@pytest.mark.asyncio
async def test_an_empty_balance_drops_openrouter_only_models():
    from unittest.mock import MagicMock

    ex = CascadeExecutor(llm=MagicMock(), tools=MagicMock(), provider_account=_Balance(0.0))
    kept = await ex.get_credits_and_filter_direct(
        ["openai/gpt-6.1-sol", "minimax/minimax-m3.1-flash", "x-ai/grok-4.7"]
    )
    assert kept == ["x-ai/grok-4.7"]


@pytest.mark.asyncio
async def test_the_balance_is_read_once_per_ttl_not_per_llm_call(monkeypatch):
    """The cascade asks before every LLM call; each ask was an HTTP round trip
    (up to 5 s) on the hot path. One answer now serves for the TTL."""
    calls = []

    async def _get(self, url, headers=None):
        calls.append(url)
        return _Resp({"limit": 10, "limit_remaining": 3.0})

    monkeypatch.setattr("httpx.AsyncClient.get", _get)
    account = OpenRouterAccountAdapter("k")
    for _ in range(5):
        assert await account.remaining_credits() == pytest.approx(3.0)
    assert len(calls) == 1
