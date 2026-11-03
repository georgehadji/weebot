"""CachingLLMAdapter — LLMPort wrapper for Anthropic prompt caching.

Injects ``cache_control: {"type": "ephemeral"}`` breakpoints into messages
before delegating to the inner adapter. This enables Anthropic's prompt
caching feature, which reduces token costs on repeated system instructions
and conversation prefixes.

Only applies to Anthropic models that support prompt caching
(Claude 3.5+ Haiku/Sonnet, Claude 3 Opus, Claude 4+).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.llm_response import LLMResponse
from weebot.infrastructure.adapters.llm.anthropic_caching_adapter import AnthropicCachingAdapter

logger = logging.getLogger(__name__)

# Every Claude family that takes cache_control except Claude 2 and Instant (H2). The old
# substring markers ("claude-3-5", "claude-4") matched no id in model_refs ("claude-sonnet-5.5"),
# so the wrapper never ran. An optional "anthropic/" prefix covers OpenRouter-style ids.
_CLAUDE_CACHEABLE = re.compile(r"^(?:anthropic/)?claude-(?!2|instant)", re.IGNORECASE)


def supports_prompt_caching(model: str) -> bool:
    """True for Claude models that accept ``cache_control`` breakpoints."""
    return bool(_CLAUDE_CACHEABLE.match(model or ""))


class CachingLLMAdapter(LLMPort):
    """LLMPort wrapper that injects Anthropic prompt-caching breakpoints.

    Wraps an inner LLMPort adapter. Before each ``chat()`` call, the
    ``AnthropicCachingAdapter.prepare_messages()`` method is called to
    inject ``cache_control`` breakpoints on the last system and user
    messages for Anthropic's prompt caching.

    Caching is only applied when:
    1. The ``enabled`` flag is ``True`` (controlled by ``LLM_ENABLE_PROMPT_CACHING``).
    2. The model name indicates Anthropic model support.

    All other ``LLMPort`` methods and keyword arguments pass through
    transparently.

    Args:
        inner_adapter: The underlying LLMPort adapter to delegate to.
        model: Model identifier string (e.g. ``"anthropic/claude-3-5-sonnet"``).
        enabled: Whether prompt-caching breakpoint injection is active.
    """

    def __init__(self, inner_adapter: LLMPort, model: str, enabled: bool = False) -> None:
        self._inner = inner_adapter
        self._model = model
        self._caching_adapter = AnthropicCachingAdapter(enabled=enabled)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Inject cache breakpoints, then delegate to inner adapter.

        When the model supports prompt caching and caching is enabled,
        ``AnthropicCachingAdapter.prepare_messages()`` is called on a
        deep copy of the message list to avoid mutating the caller's
        messages.

        If the cache hit rate on system messages drops significantly over
        time, a WARN log is emitted to signal a possible system-prompt
        restructuring opportunity.
        """
        effective_model = model or self._model
        if self._caching_adapter.enabled and supports_prompt_caching(effective_model):
            messages = self._caching_adapter.prepare_messages(messages)
            logger.debug(
                "CachingLLMAdapter: injected cache_control breakpoints for %s", effective_model
            )

        response = await self._inner.chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Telemetry: warn if the system prompt appears to have been rebuilt
        # (detected by an unusually short input context for the model).
        # This is a heuristic — true cache-miss telemetry requires the
        # provider's cache-creation/fill response headers.
        if self._caching_adapter.enabled and supports_prompt_caching(effective_model):
            _log_cache_telemetry(effective_model, response)

        return response


def cache_read_ratio(usage: dict[str, int] | None) -> float | None:
    """Share of input tokens served from the provider's prompt cache, or None if unreported.

    OpenAI-style usage counts cached tokens inside ``prompt_tokens``. Anthropic's
    ``input_tokens`` excludes them; its adapter marks that with ``cache_write_tokens``.
    """
    if not usage:
        return None
    prompt = usage.get("prompt_tokens", 0) or 0
    cached = usage.get("cached_tokens", 0) or 0
    total = prompt + cached if "cache_write_tokens" in usage else prompt
    return cached / total if total else None


def _log_cache_telemetry(model: str, response: LLMResponse) -> None:
    """Log the cache-read ratio and count cache-read tokens (H2).

    The old version read ``usage["input_tokens"]``, a key no adapter emits, so it saw 0 on
    every call and warned every time.
    """
    usage = getattr(response, "usage", None)
    ratio = cache_read_ratio(usage)
    if ratio is None:
        return
    cached = usage.get("cached_tokens", 0) or 0
    logger.debug("Prompt cache: %s read ratio %.2f (%d tokens)", model, ratio, cached)
    if cached:
        from weebot.infrastructure.observability import metrics

        metrics.llm_cache_read_tokens_total.labels(model=model).inc(cached)
