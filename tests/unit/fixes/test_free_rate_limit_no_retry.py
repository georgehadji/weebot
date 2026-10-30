"""Wave 5 free-provider follow-up: a free model's 429 goes straight to the cascade.

``ResilientLLMAdapter`` treats a rate limit as BACKOFF and retried it six times, about a
minute, before the cascade could try the next model. A free tier that answers 429 has
usually spent its daily quota, so the wait buys nothing: the free adapter no longer retries
rate limits. Other transient errors are still retried, and paid models keep the backoff.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.config.settings import get_settings
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter

GROQ_ID = "free/groq/openai/gpt-oss-120b"


class _Failing:
    def __init__(self, message: str) -> None:
        self.calls = 0
        self._message = message

    async def chat(self, **kwargs):
        self.calls += 1
        raise RuntimeError(self._message)


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    async def _sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)


@pytest.fixture
def free_adapter(monkeypatch):
    monkeypatch.setenv("WEEBOT_FREE_ROLES", "executor=groq/openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    get_settings.cache_clear()
    yield AdapterFactory().create_adapter("free", model=GROQ_ID, enable_circuit_breaker=False)
    get_settings.cache_clear()


async def _call(adapter, inner) -> None:
    adapter._inner = inner
    with pytest.raises(RuntimeError):
        await adapter.chat(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_a_free_model_rate_limit_is_not_retried(free_adapter):
    inner = _Failing("Error code: 429 - Too Many Requests")
    await _call(free_adapter, inner)
    assert inner.calls == 1


@pytest.mark.asyncio
async def test_a_free_model_server_error_is_still_retried(free_adapter):
    inner = _Failing("Error code: 503 - Service Unavailable")
    await _call(free_adapter, inner)
    assert inner.calls > 1


@pytest.mark.asyncio
async def test_a_paid_model_rate_limit_is_still_retried():
    inner = _Failing("Error code: 429 - Too Many Requests")
    adapter = ResilientLLMAdapter(inner, "openrouter/x", enable_circuit_breaker=False)
    await _call(adapter, inner)
    assert inner.calls > 1
