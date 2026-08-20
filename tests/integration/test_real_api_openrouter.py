"""Integration tests — real OpenRouter API calls.

Verifies that the LLM adapter stack (AdapterFactory → ResilientLLMAdapter →
OpenRouterAdapter) correctly sends requests to the OpenRouter API and returns
valid responses.

These tests require a valid OPENROUTER_API_KEY in the environment or .env file.
They are marked with ``@pytest.mark.external`` and gated behind
``WEEBOT_TEST_LIVE=1`` so a bare ``pytest`` never makes a live, billed call.

Usage:
    # Run only live tests
    WEEBOT_TEST_LIVE=1 pytest tests/integration/test_real_api_openrouter.py -v -m external

    # Default — safe for CI, no secrets needed
    pytest tests/integration/ -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory

# ═════════════════════════════════════════════════════════════════════════════
# Load .env if present (so tests work without manual export)
# ═════════════════════════════════════════════════════════════════════════════


def _load_dotenv() -> None:
    """Load .env file from project root into os.environ."""
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
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# ═════════════════════════════════════════════════════════════════════════════
# Skip markers
# ═════════════════════════════════════════════════════════════════════════════

_LIVE = os.environ.get("WEEBOT_TEST_LIVE", "").strip().lower() in ("1", "true", "yes")
_SKIP = pytest.mark.skipif(not _LIVE, reason="Set WEEBOT_TEST_LIVE=1 to run live-network tests")

_real_api_reason: str | None = None
if not os.getenv("OPENROUTER_API_KEY"):
    _real_api_reason = "OPENROUTER_API_KEY not set — export it or add to .env"

needs_openrouter = pytest.mark.skipif(
    _real_api_reason is not None, reason=_real_api_reason or "OPENROUTER_API_KEY not set"
)


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def factory() -> AdapterFactory:
    """Reuse the same factory (and cached adapters) across tests."""
    return AdapterFactory()


@pytest.fixture
def adapter(factory: AdapterFactory) -> LLMPort:
    """OpenRouter adapter targeting a free model to keep costs minimal.

    ``microsoft/phi-4-mini-instruct`` is a strong free model available
    on OpenRouter with generous rate limits.  Falls back to
    ``google/gemini-2.0-flash-001`` (also free) if Phi is unavailable.
    """
    return factory.create_adapter(provider="openrouter", model="microsoft/phi-4-mini-instruct")


# ═════════════════════════════════════════════════════════════════════════════
# Basic chat tests
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_simple_chat_returns_content(adapter: LLMPort):
    """A simple one-message chat should return non-empty content."""
    response = await adapter.chat(
        messages=[{"role": "user", "content": "Say exactly: hello world"}]
    )

    assert isinstance(response, LLMResponse)
    assert response.content is not None, "Response must have content"
    assert len(response.content.strip()) > 0, "Response content must not be empty"
    assert (
        "hello" in response.content.lower()
    ), f"Expected 'hello' in response, got: {response.content!r}"


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_multi_turn_conversation(adapter: LLMPort):
    """A multi-turn conversation should maintain context."""
    messages = [
        {"role": "user", "content": "My name is TestBot. Remember it."},
        {"role": "assistant", "content": "Got it, your name is TestBot."},
        {"role": "user", "content": "What is my name?"},
    ]
    response = await adapter.chat(messages=messages)

    assert response.content is not None
    assert (
        "TestBot" in response.content
    ), f"Expected 'TestBot' in multi-turn response, got: {response.content!r}"


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_system_prompt_influences_response(adapter: LLMPort):
    """A system prompt should influence the assistant's style."""
    messages = [
        {"role": "system", "content": "You are a pirate. Always end responses with 'Arrr!'."},
        {"role": "user", "content": "What is Python?"},
    ]
    response = await adapter.chat(messages=messages)

    assert response.content is not None
    assert (
        "Arrr" in response.content
    ), f"Expected 'Arrr!' in pirate response, got: {response.content!r}"


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_json_response_mode(adapter: LLMPort):
    """JSON response_format should produce parseable JSON."""
    response = await adapter.chat(
        messages=[
            {"role": "system", "content": "Respond only with valid JSON."},
            {"role": "user", "content": 'Return {"language": "Python", "year": 1991}'},
        ],
        response_format={"type": "json_object"},
    )

    assert response.content is not None
    import json

    try:
        data = json.loads(response.content)
        assert "language" in data, f"JSON missing 'language' key: {data}"
    except json.JSONDecodeError:
        pytest.fail(f"Response was not valid JSON: {response.content!r}")


# ═════════════════════════════════════════════════════════════════════════════
# Resilience tests
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_usage_tokens_are_populated(adapter: LLMPort):
    """A successful call should populate usage tokens."""
    response = await adapter.chat(messages=[{"role": "user", "content": "Count to 3: 1, 2, 3."}])

    assert response.usage is not None, "Usage must be populated by resilient adapter"
    # Prompt tokens should always be > 0
    prompt_tokens = response.usage.get("prompt_tokens", 0)
    assert prompt_tokens > 0, f"Expected prompt_tokens > 0, got {prompt_tokens}"
    # Completion tokens should be > 0 for a non-empty response
    completion_tokens = response.usage.get("completion_tokens", 0)
    assert completion_tokens > 0, f"Expected completion_tokens > 0, got {completion_tokens}"


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_adapter_caching(factory: AdapterFactory):
    """Repeated adapter creation should return the cached instance."""
    a1 = factory.create_adapter("openrouter", model="microsoft/phi-4-mini-instruct")
    a2 = factory.create_adapter("openrouter", model="microsoft/phi-4-mini-instruct")
    assert a1 is a2, "Adapter factory should cache adapters"


@pytest.mark.external
@_SKIP
@needs_openrouter
@pytest.mark.asyncio
async def test_long_prompt_handled(adapter: LLMPort):
    """A moderately long prompt should be handled without errors."""
    long_text = "The quick brown fox jumps over the lazy dog. " * 50  # ~2,200 chars
    response = await adapter.chat(
        messages=[{"role": "user", "content": f"Summarize in one sentence: {long_text}"}]
    )

    assert response.content is not None
    assert len(response.content) > 0
    # The summary should be shorter than the input
    assert len(response.content) < len(long_text), "Summary should be shorter than input"
