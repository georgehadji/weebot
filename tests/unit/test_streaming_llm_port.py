"""Tests for StreamingLLMPort protocol + NonStreamingLLMAdapter (T1.1).

Verifies:
  1. isinstance() is True only for adapters that define stream().
  2. The fallback adapter yields exactly one chunk whose content equals
     what chat() would have returned — callers get a uniform code path
     regardless of whether the underlying provider can stream.
  3. as_streaming() passes a real streaming adapter through unchanged.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from weebot.application.ports.llm_port import LLMPort
from weebot.application.ports.streaming_llm_port import StreamingLLMPort
from weebot.domain.models.llm_response import LLMChunk, LLMResponse
from weebot.infrastructure.adapters.non_streaming_llm_adapter import (
    NonStreamingLLMAdapter,
    as_streaming,
)


class _NonStreamingAdapter(LLMPort):
    """Bare LLMPort — no stream() method, like most real adapters today."""

    async def chat(self, messages, tools=None, tool_choice="auto",
                    response_format=None, model=None, temperature=None,
                    max_tokens=None) -> LLMResponse:
        return LLMResponse(content="full response", model="stub-model", usage={"total_tokens": 10})


class _StreamingAdapter(LLMPort):
    """An adapter that additionally implements stream()."""

    async def chat(self, messages, tools=None, tool_choice="auto",
                    response_format=None, model=None, temperature=None,
                    max_tokens=None) -> LLMResponse:
        return LLMResponse(content="unused", model="stub-model")

    async def stream(self, messages, tools=None, tool_choice="auto",
                      model=None, temperature=None, max_tokens=None) -> AsyncIterator[LLMChunk]:
        yield LLMChunk(delta="chunk-1", model="stub-model")
        yield LLMChunk(delta="chunk-2", model="stub-model", finish_reason="stop")


def test_isinstance_true_only_for_adapters_implementing_stream():
    assert not isinstance(_NonStreamingAdapter(), StreamingLLMPort)
    assert isinstance(_StreamingAdapter(), StreamingLLMPort)


@pytest.mark.asyncio
async def test_fallback_adapter_yields_one_chunk_matching_chat_response():
    inner = _NonStreamingAdapter()
    fallback = NonStreamingLLMAdapter(inner)

    chunks = [c async for c in fallback.stream(messages=[{"role": "user", "content": "hi"}])]

    assert len(chunks) == 1
    assert chunks[0].delta == "full response"
    assert chunks[0].model == "stub-model"
    assert chunks[0].finish_reason == "stop"
    assert chunks[0].usage == {"total_tokens": 10}


@pytest.mark.asyncio
async def test_as_streaming_wraps_non_streaming_adapter():
    wrapped = as_streaming(_NonStreamingAdapter())
    assert isinstance(wrapped, NonStreamingLLMAdapter)
    chunks = [c async for c in wrapped.stream(messages=[])]
    assert chunks[0].delta == "full response"


def test_as_streaming_passes_through_real_streaming_adapter():
    real = _StreamingAdapter()
    assert as_streaming(real) is real
