"""Integration tests — real LLM API calls (DeepSeek).

Verifies that the LLM adapter stack (AdapterFactory → ResilientLLMAdapter →
DeepSeekAdapter) correctly sends requests to the DeepSeek API and returns valid
responses.

These tests require a valid DEEPSEEK_API_KEY in the environment or .env file.
They are marked with ``@pytest.mark.real_api`` so they can be selected or
excluded independently.

Usage:
    pytest tests/integration/test_real_api.py -v -m real_api
    pytest tests/integration/ -v -m "not real_api"  # CI-safe
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory


# ═════════════════════════════════════════════════════════════════════════════
# Load .env
# ═════════════════════════════════════════════════════════════════════════════

def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        # Always set – force override any stale pytest session values
        if key:
            os.environ[key] = value

_load_dotenv()


# ═════════════════════════════════════════════════════════════════════════════
# Skip markers
# ═════════════════════════════════════════════════════════════════════════════

_real_api_reason: str | None = None
if not os.getenv("DEEPSEEK_API_KEY"):
    _real_api_reason = "DEEPSEEK_API_KEY not set"

needs_deepseek = pytest.mark.skipif(
    _real_api_reason is not None,
    reason=_real_api_reason or "DEEPSEEK_API_KEY not set",
)


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="function")
def factory() -> AdapterFactory:
    """Fresh factory per test — avoid cached adapter from prior tests."""
    f = AdapterFactory()
    f.clear_cache()
    return f


@pytest.fixture
def adapter(factory: AdapterFactory) -> LLMPort:
    """DeepSeek adapter.

    deepseek-chat routes to deepseek-v4-flash (fast, free-tier compatible).
    Retry is disabled to avoid tripping API rate limits on the free tier.
    API key is passed explicitly to avoid dotenv/pytest ordering issues.
    """
    return factory.create_adapter(
        provider="deepseek",
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        enable_retry=False,
        enable_circuit_breaker=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Basic chat
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.real_api
@needs_deepseek
@pytest.mark.asyncio
async def test_simple_chat_returns_content(adapter: LLMPort):
    response = await adapter.chat(
        messages=[{"role": "user", "content": "Say exactly: hello world"}],
    )
    assert isinstance(response, LLMResponse)
    assert response.content
    assert "hello" in response.content.lower()


@pytest.mark.real_api
@needs_deepseek
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
@needs_deepseek
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
@needs_deepseek
@pytest.mark.asyncio
async def test_json_response_mode(adapter: LLMPort):
    import json
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
@needs_deepseek
@pytest.mark.asyncio
async def test_usage_tokens_are_populated(adapter: LLMPort):
    response = await adapter.chat(
        messages=[{"role": "user", "content": "Count to 3: 1, 2, 3."}],
    )
    assert response.usage is not None
    assert response.usage.get("prompt_tokens", 0) > 0
    assert response.usage.get("completion_tokens", 0) > 0


@pytest.mark.real_api
@needs_deepseek
@pytest.mark.asyncio
async def test_adapter_caching():
    """Within a single factory, repeated adapter creation returns cached instance."""
    f = AdapterFactory()
    a1 = f.create_adapter("deepseek", model="deepseek-chat")
    a2 = f.create_adapter("deepseek", model="deepseek-chat")
    assert a1 is a2


@pytest.mark.real_api
@needs_deepseek
@pytest.mark.asyncio
async def test_long_prompt_handled(adapter: LLMPort):
    long_text = "The quick brown fox jumps over the lazy dog. " * 50
    response = await adapter.chat(
        messages=[{"role": "user", "content": f"Summarize in one sentence: {long_text}"}],
    )
    assert response.content
    assert len(response.content) < len(long_text)
