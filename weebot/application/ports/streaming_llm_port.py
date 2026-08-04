"""StreamingLLMPort — structural interface for token-streaming adapters.

A ``typing.Protocol`` rather than an ``abc.ABC`` deliberately: ``LLMPort``
already has ~20 concrete adapters (OpenAI-compatible, Anthropic, DeepSeek,
resilient wrappers, caching wrappers...). Widening ``LLMPort`` itself with
an abstract ``stream()`` method would force every one of them to grow a
method whether or not its provider supports streaming. A structural
protocol lets adapters opt in by simply defining ``stream`` — existing
adapters need zero changes, and ``isinstance(adapter, StreamingLLMPort)``
still works at runtime because the protocol is ``@runtime_checkable``.

Adapters that cannot stream are wrapped in ``NonStreamingLLMAdapter``
(see ``infrastructure/adapters/non_streaming_llm_adapter.py``) so callers
have exactly one code path: check once, wrap if needed, always call
``.stream()``.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable

from weebot.domain.models.llm_response import LLMChunk


@runtime_checkable
class StreamingLLMPort(Protocol):
    """Structural interface for LLM adapters that can stream partial output."""

    def stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[LLMChunk]:
        """Stream a chat completion as a sequence of ``LLMChunk`` deltas."""
        ...
