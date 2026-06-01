"""Integration tests — real OpenRouter API calls.

Verifies that the LLM adapter stack (AdapterFactory → ResilientLLMAdapter →
OpenRouterAdapter) correctly sends requests to the OpenRouter API and returns
valid responses.

These tests require a valid OPENROUTER_API_KEY in the environment or .env file.
They are marked with ``@pytest.mark.real_api`` so they can be selected or
excluded independently.

Usage:
    pytest tests/integration/test_real_api.py -v -m real_api
    pytest tests/integration/ -v -m "not real_api"  # CI-safe
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory


# ═════════════════════════════════════════════════════════════════════════════
# Skip marker
# ═════════════════════════════════════════════════════════════════════════════

_real_api_reason: str | None = None
if not os.getenv("OPENROUTER_API_KEY"):
    _real_api_reason = "OPENROUTER_API_KEY not set"

needs_router = pytest.mark.skipif(
    _real_api_reason is not None,
    reason=_real_api_reason or "OPENROUTER_API_KEY not set",
)


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="function")
def factory() -> AdapterFactory:
    """Fresh factory per test to avoid cached adapters across tests."""
    f = AdapterFactory()
    f.clear_cache()
    return f


@pytest.fixture
def adapter(factory: AdapterFactory) -> LLMPort:
    """OpenRouter adapter — uses free models to keep costs minimal.

    ``microsoft/phi-4-mini-instruct`` is a strong free model on OpenRouter.
    Retry is disabled for tests to avoid tripping rate limits.
    """
    return factory.create_adapter(
        provider="openrouter",
        model="microsoft/phi-4-mini-instruct",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        enable_retry=False,
        enable_circuit_breaker=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Basic chat
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_simple_chat_returns_content(adapter: LLMPort):
    response = await adapter.chat(
        messages=[{"role": "user", "content": "Say exactly: hello world"}],
    )
    assert isinstance(response, LLMResponse)
    assert response.content
    assert "hello" in response.content.lower()


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_multi_turn_conversation(adapter: LLMPort):
    messages = [
        {"role": "user", "content": "My name is TestBot. Remember it."},
        {"role": "assistant", "content": "Got it, your name is TestBot."},
        {"role": "user", "content": "What is my name?"},
    ]
    response = await adapter.chat(messages=messages)
    assert response.content
    assert "TestBot" in response.content


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_system_prompt_influences_response(adapter: LLMPort):
    messages = [
        {"role": "system", "content": "You are a pirate. End every response with 'Arrr!'."},
        {"role": "user", "content": "Yes or no: is water wet?"},
    ]
    response = await adapter.chat(messages=messages)
    assert response.content
    assert "Arrr" in response.content


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_json_response_mode(adapter: LLMPort):
    response = await adapter.chat(
        messages=[
            {"role": "system", "content": "Respond only with valid JSON."},
            {"role": "user", "content": 'Return {"language": "Python", "year": 1991}'},
        ],
        response_format={"type": "json_object"},
    )
    assert response.content
    data = json.loads(response.content)
    assert "language" in data


# ═════════════════════════════════════════════════════════════════════════════
# Resilience / metrics
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_usage_tokens_are_populated(adapter: LLMPort):
    response = await adapter.chat(
        messages=[{"role": "user", "content": "Count to 3: 1, 2, 3."}],
    )
    assert response.usage is not None
    assert response.usage.get("prompt_tokens", 0) > 0
    assert response.usage.get("completion_tokens", 0) > 0


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_adapter_caching():
    """Within a single factory, repeated adapter creation returns cached instance."""
    f = AdapterFactory()
    a1 = f.create_adapter("openrouter", model="microsoft/phi-4-mini-instruct")
    a2 = f.create_adapter("openrouter", model="microsoft/phi-4-mini-instruct")
    assert a1 is a2


@pytest.mark.real_api
@needs_router
@pytest.mark.asyncio
async def test_long_prompt_handled(adapter: LLMPort):
    long_text = "The quick brown fox jumps over the lazy dog. " * 50
    response = await adapter.chat(
        messages=[{"role": "user", "content": f"Summarize in one sentence: {long_text}"}],
    )
    assert response.content
    assert len(response.content) < len(long_text)
