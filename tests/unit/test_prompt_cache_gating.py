"""Prompt caching is on for Claude routes and independent of the response cache (H2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.infrastructure.adapters.llm.adapter_factory import AdapterFactory
from weebot.infrastructure.adapters.llm.anthropic_adapter import AnthropicAdapter
from weebot.infrastructure.adapters.llm.caching_llm_adapter import CachingLLMAdapter


def _wrapped_by_caching(adapter) -> bool:
    node, seen = adapter, 0
    while node is not None and seen < 6:
        if isinstance(node, CachingLLMAdapter):
            return True
        node = getattr(node, "_primary", None) or getattr(node, "_inner", None)
        seen += 1
    return False


def test_claude_is_wrapped_when_only_the_prompt_flag_is_set(monkeypatch):
    monkeypatch.delenv("LLM_ENABLE_CACHING", raising=False)
    monkeypatch.setenv("LLM_ENABLE_PROMPT_CACHING", "1")
    factory = AdapterFactory()
    adapter = factory.create_adapter("openrouter", model="anthropic/claude-sonnet-5.5", api_key="k")
    assert _wrapped_by_caching(adapter)
    assert factory._enable_caching is False  # the response cache stays off


def test_prompt_caching_is_on_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("LLM_ENABLE_PROMPT_CACHING", raising=False)
    assert AdapterFactory()._enable_prompt_caching is True
    off = AdapterFactory(enable_prompt_caching=False).create_adapter(
        "openrouter", model="anthropic/claude-sonnet-5.5", api_key="k2"
    )
    assert not _wrapped_by_caching(off)


def test_non_claude_models_are_never_wrapped():
    adapter = AdapterFactory(enable_prompt_caching=True).create_adapter(
        "openrouter", model="moonshotai/kimi-k3.1-pro", api_key="k3"
    )
    assert not _wrapped_by_caching(adapter)


@pytest.mark.asyncio
async def test_anthropic_usage_carries_the_cache_fields():
    adapter = AnthropicAdapter(api_key="k", default_model="claude-sonnet-5-5")
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hi")],
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(
            input_tokens=200,
            output_tokens=10,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=50,
        ),
    )
    adapter._client = MagicMock()
    adapter._client.messages.create = AsyncMock(return_value=response)
    result = await adapter.chat(messages=[{"role": "system", "content": "s"},
                                          {"role": "user", "content": "u"}])
    assert result.usage["cached_tokens"] == 800
    assert result.usage["cache_write_tokens"] == 50
    assert result.usage["prompt_tokens"] == 200
    sent = adapter._client.messages.create.call_args.kwargs
    # Anthropic rejects role "system" inside messages=; it belongs in system=.
    assert all(m["role"] != "system" for m in sent["messages"])
    assert sent["system"] == [{"type": "text", "text": "s"}]


def test_cache_markers_move_onto_content_blocks():
    from weebot.infrastructure.adapters.llm.anthropic_adapter import _split_system

    marker = {"type": "ephemeral"}
    system, rest = _split_system(
        [
            {"role": "system", "content": "s", "cache_control": marker},
            {"role": "user", "content": "u", "cache_control": marker},
        ]
    )
    assert system == [{"type": "text", "text": "s", "cache_control": marker}]
    assert rest == [
        {"role": "user", "content": [{"type": "text", "text": "u", "cache_control": marker}]}
    ]
