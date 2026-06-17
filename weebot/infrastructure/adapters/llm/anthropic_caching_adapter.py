"""Anthropic Prompt Caching Adapter — injects cache_control breakpoints.

Wraps an existing LLM provider adapter to add ephemeral cache control
breakpoints for Anthropic/OpenRouter prompt caching support.

This adapter is a decorator/wrapper around any LLM provider that sends
messages to Anthropic-compatible endpoints (direct Anthropic API or
OpenRouter with Anthropic models).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AnthropicCachingAdapter:
    """Wraps LLM provider calls to inject cache_control breakpoints.

    Usage:
        caching_adapter = AnthropicCachingAdapter(prompt_caching_enabled=True)
        messages = caching_adapter.prepare_messages(raw_messages)

    The adapter injects ``cache_control: {"type": "ephemeral"}`` on specific
    messages in the message list to enable Anthropic's prompt caching.

    Per Anthropic's docs:
    - System messages: cache the system instruction
    - First user message: can be cached as part of the system context
    - Multiple system messages: each can have cache_control
    """

    def __init__(
        self,
        enabled: bool = False,
        ttl_seconds: int = 300,
        max_cached_sections: int = 3,
    ) -> None:
        self._enabled = enabled
        self._ttl_seconds = ttl_seconds
        self._max_cached_sections = max_cached_sections

    def prepare_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Prepare messages with cache_control breakpoints.

        If caching is disabled, returns messages unchanged.
        If enabled, adds ``cache_control: {"type": "ephemeral"}`` to
        the last system message and the last user message before any
        assistant response.
        """
        if not self._enabled:
            return messages

        result = list(messages)
        cache_markers_added = 0

        # 1. Cache the last system message
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "system" and cache_markers_added < self._max_cached_sections:
                result[i] = {**result[i], "cache_control": {"type": "ephemeral"}}
                cache_markers_added += 1
                break

        # 2. Cache the last user message before any assistant responses
        if cache_markers_added < self._max_cached_sections:
            first_assistant = -1
            for i, msg in enumerate(result):
                if msg.get("role") == "assistant":
                    first_assistant = i
                    break

            if first_assistant > 0:
                for i in range(first_assistant - 1, -1, -1):
                    if result[i].get("role") == "user" and cache_markers_added < self._max_cached_sections:
                        result[i] = {**result[i], "cache_control": {"type": "ephemeral"}}
                        cache_markers_added += 1
                        break

        logger.debug(
            "AnthropicCachingAdapter: added %d cache_control markers (enabled=%s)",
            cache_markers_added, self._enabled,
        )
        return result

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds
