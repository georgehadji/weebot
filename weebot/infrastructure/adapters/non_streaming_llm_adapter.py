"""NonStreamingLLMAdapter — Null Object fallback giving every LLMPort a .stream().

Wraps an adapter that does not implement ``StreamingLLMPort`` and exposes
a ``stream()`` method that calls the ordinary ``chat()`` and yields the
whole response as a single ``LLMChunk``. Callers never need to branch on
whether the underlying provider can stream — they check once
(``isinstance(adapter, StreamingLLMPort)``), wrap if not, and always call
``.stream()``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Union

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.llm_response import LLMChunk

if TYPE_CHECKING:
    from weebot.application.ports.streaming_llm_port import StreamingLLMPort


class NonStreamingLLMAdapter:
    """Adapts any ``LLMPort`` to the ``StreamingLLMPort`` shape via one chunk."""

    def __init__(self, inner: LLMPort) -> None:
        self._inner = inner

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[LLMChunk]:
        response = await self._inner.chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        yield LLMChunk(
            delta=response.content,
            tool_call_deltas=response.tool_calls or None,
            finish_reason="stop",
            model=response.model,
            usage=response.usage or None,
        )


def as_streaming(llm: LLMPort) -> Union[LLMPort, "StreamingLLMPort"]:
    """Return *llm* unchanged if it already streams, else wrap it.

    The single call site every caller should use instead of hand-rolling
    the isinstance check.
    """
    from weebot.application.ports.streaming_llm_port import StreamingLLMPort

    if isinstance(llm, StreamingLLMPort):
        return llm
    return NonStreamingLLMAdapter(llm)
