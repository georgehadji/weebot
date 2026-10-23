"""Claude prompt caching fires on the OpenRouter path.

Found by the 2026-10-23 audit against OpenRouter's prompt-caching guide: the
only caching path (`CachingLLMAdapter`) was off by default, matched no Claude
4.x/5.x id, was chosen by the model the factory was built with rather than
the model of each call (the cascade switches models per call on one
adapter), and put breakpoints where OpenRouter does not read them. So Claude
input was never cached. OpenRouter's automatic caching is one top-level
`cache_control` field; it is added per call for `anthropic/` models on tool
loops, which resend the same prefix every turn. One-shot calls skip it, since
a cache write costs 1.25x input.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter

_TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]


def _kwargs(model: str, tools=_TOOLS) -> dict:
    adapter = OpenAIAdapter(api_key="sk-or-v1-test", default_model=model)
    return adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=tools, model=model
    )


def _extra(kw: dict) -> dict:
    return kw.get("extra_body") or {}


def test_a_claude_tool_loop_asks_openrouter_to_cache():
    assert _extra(_kwargs("anthropic/claude-sonnet-5.5"))["cache_control"] == {"type": "ephemeral"}


def test_a_one_shot_claude_call_does_not_pay_for_a_cache_write():
    assert "cache_control" not in _extra(_kwargs("anthropic/claude-haiku-5.5", tools=None))


def test_other_vendors_are_left_to_their_own_automatic_caching():
    assert "cache_control" not in _extra(_kwargs("deepseek/deepseek-v4.1-flash"))


@pytest.mark.asyncio
async def test_cached_tokens_are_reported_in_usage():
    adapter = OpenAIAdapter(api_key="sk-or-v1-test", default_model="anthropic/claude-sonnet-5.5")
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=10,
        total_tokens=1010,
        prompt_tokens_details=SimpleNamespace(cached_tokens=900),
    )
    message = SimpleNamespace(content="ok", tool_calls=None)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=usage,
        model="anthropic/claude-sonnet-5.5",
    )

    async def _create(**kw):
        return response

    adapter._client.chat.completions.create = _create
    resp = await adapter.chat(messages=[{"role": "user", "content": "hi"}])
    assert resp.usage["cached_tokens"] == 900
