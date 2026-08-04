"""Tests for OpenAIAdapter.stream() (T1.2).

Verifies:
  1. Content chunks translate to LLMChunk deltas in order.
  2. A trailing usage-only chunk (no choices) still yields an LLMChunk
     carrying usage, matching the OpenAI streaming shape when
     stream_options={"include_usage": True} is set.
  3. tool_call deltas pass through with index/id/function fields intact.
  4. stream=True and stream_options are always sent.
  5. A rate limit before any chunk is yielded falls back to the next
     model in the chain, matching chat()'s pre-response fallback.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import RateLimitError

from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "http://test.local/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _fake_chunk(content=None, tool_calls=None, finish_reason=None, usage=None, model="stub-model"):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model=model, usage=usage)


def _usage_only_chunk(model="stub-model"):
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=7, total_tokens=12)
    return SimpleNamespace(choices=[], model=model, usage=usage)


async def _async_iter(items):
    for item in items:
        yield item


@pytest.fixture
def adapter():
    a = OpenAIAdapter(api_key="test-key", base_url="http://test.local")
    return a


@pytest.mark.asyncio
async def test_stream_yields_content_chunks_in_order(adapter):
    chunks = [
        _fake_chunk(content="Hel"),
        _fake_chunk(content="lo"),
        _fake_chunk(content="", finish_reason="stop"),
    ]
    adapter._client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

    received = [c async for c in adapter.stream(messages=[{"role": "user", "content": "hi"}])]

    assert [c.delta for c in received] == ["Hel", "lo", ""]
    assert received[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_trailing_usage_only_chunk_yields_usage(adapter):
    chunks = [
        _fake_chunk(content="hi", finish_reason="stop"),
        _usage_only_chunk(),
    ]
    adapter._client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

    received = [c async for c in adapter.stream(messages=[{"role": "user", "content": "hi"}])]

    assert len(received) == 2
    assert received[1].usage == {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
    assert received[1].delta == ""


@pytest.mark.asyncio
async def test_stream_tool_call_deltas_pass_through(adapter):
    tc = SimpleNamespace(
        index=0, id="call_1",
        function=SimpleNamespace(name="search", arguments='{"q":'),
    )
    chunks = [_fake_chunk(tool_calls=[tc], finish_reason="tool_calls")]
    adapter._client.chat.completions.create = AsyncMock(return_value=_async_iter(chunks))

    received = [c async for c in adapter.stream(messages=[{"role": "user", "content": "hi"}])]

    assert received[0].tool_call_deltas == [
        {"index": 0, "id": "call_1", "function": {"name": "search", "arguments": '{"q":'}}
    ]


@pytest.mark.asyncio
async def test_stream_always_sends_stream_true_and_usage_option(adapter):
    create_mock = AsyncMock(return_value=_async_iter([_fake_chunk(content="hi")]))
    adapter._client.chat.completions.create = create_mock

    _ = [c async for c in adapter.stream(messages=[{"role": "user", "content": "hi"}])]

    call_kwargs = create_mock.call_args.kwargs
    assert call_kwargs["stream"] is True
    assert call_kwargs["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_falls_back_on_pre_stream_rate_limit(adapter, monkeypatch):
    monkeypatch.setattr(
        "weebot.config.model_refs.MODEL_FALLBACK_NON_OPENROUTER", "fallback/model-x"
    )
    fallback_chunks = [_fake_chunk(content="from fallback", model="fallback/model-x")]

    create_mock = AsyncMock(side_effect=[_rate_limit_error(), _async_iter(fallback_chunks)])
    adapter._client.chat.completions.create = create_mock

    received = [c async for c in adapter.stream(messages=[{"role": "user", "content": "hi"}], model="primarymodel")]

    assert len(received) == 1
    assert received[0].delta == "from fallback"
    assert create_mock.call_count == 2
