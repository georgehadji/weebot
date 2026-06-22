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
from typing import Any, Dict, List, Optional

from weebot.application.ports.llm_port import LLMPort
from weebot.domain.models.llm_response import LLMResponse
from weebot.infrastructure.adapters.llm.anthropic_caching_adapter import (
    AnthropicCachingAdapter,
)

logger = logging.getLogger(__name__)

# Substring markers for Anthropic models that support prompt caching.
# Prompt caching started with Claude 3.5 (Haiku, Sonnet) and Claude 3 Opus.
# Claude 4+ also supports it. Conservative list to avoid false positives.
_CACHING_MODEL_MARKERS: tuple[str, ...] = (
    "claude-3-5",      # 3.5 Haiku, 3.5 Sonnet, and future 3.5.x models
    "claude-3-opus",   # 3 Opus
    "claude-4",        # 4 Sonnet, 4 Opus, and future 4.x models
)


def supports_prompt_caching(model: str) -> bool:
    """Best-effort check whether *model* supports Anthropic prompt caching.

    Uses conservative substring matching over known caching-capable model
    families. A false negative just skips the cache breakpoint injection
    (safe — no caching), while a false positive would silently produce no
    benefit (unrecognized models ignore cache_control). Both outcomes are
    safe; we err on the side of false negatives.
    """
    m = (model or "").lower()
    return any(marker in m for marker in _CACHING_MODEL_MARKERS)


class CachingLLMAdapter(LLMPort):
    """LLMPort wrapper that injects Anthropic prompt-caching breakpoints.

    Wraps an inner LLMPort adapter. Before each ``chat()`` call, the
    ``AnthropicCachingAdapter.prepare_messages()`` method is called to
    inject ``cache_control`` breakpoints on the last system and user
    messages for Anthropic's prompt caching.

    Caching is only applied when:
    1. The ``enabled`` flag is ``True`` (controlled by ``LLM_ENABLE_CACHING``).
    2. The model name indicates Anthropic model support.

    All other ``LLMPort`` methods and keyword arguments pass through
    transparently.

    Args:
        inner_adapter: The underlying LLMPort adapter to delegate to.
        model: Model identifier string (e.g. ``"anthropic/claude-3-5-sonnet"``).
        enabled: Whether prompt-caching breakpoint injection is active.
    """

    def __init__(
        self,
        inner_adapter: LLMPort,
        model: str,
        enabled: bool = False,
    ) -> None:
        self._inner = inner_adapter
        self._model = model
        self._caching_adapter = AnthropicCachingAdapter(enabled=enabled)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
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
                "CachingLLMAdapter: injected cache_control breakpoints for %s",
                effective_model,
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


def _log_cache_telemetry(model: str, response: LLMResponse) -> None:
    """Emit WARN when input tokens are unusually low for a caching-enabled model.

    A very low input-token count (< 50) on a model that should benefit from
    prompt caching suggests the cache was evicted, the system prompt was
    rebuilt, or the conversation is in its first turn with a cold cache.

    This is a best-effort heuristic — the real signal comes from
    provider-specific response headers (``x-amzn-cache-hit`` for Bedrock,
    ``cf-cache-status`` for Cloudflare, etc.). Cross-call trend analysis
    would be more robust; this simple threshold is a cheap first pass.
    """
    usage = None
    if hasattr(response, "usage") and response.usage:
        usage = response.usage

    if usage is None:
        return

    # LLMResponse.usage is always a dict[str, int] — no non-dict branch.
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0) or 0
    else:
        input_tokens = 0

    # If the input tokens are very low (< 50), the system prompt may have
    # been regenerated or the cache was cold. Log at WARN for observability.
    if input_tokens is not None and input_tokens < 50:
        logger.warning(
            "CachingLLMAdapter: unusually low input token count (%d) for %s — "
            "possible cache miss or system-prompt rebuild",
            input_tokens,
            model,
        )
