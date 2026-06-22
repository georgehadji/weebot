"""Anthropic Prompt Caching Adapter — injects cache_control breakpoints.

Wraps an existing LLM provider adapter to add ephemeral cache control
breakpoints for Anthropic/OpenRouter prompt caching support.

This adapter is a decorator/wrapper around any LLM provider that sends
messages to Anthropic-compatible endpoints (direct Anthropic API or
OpenRouter with Anthropic models).
"""
from __future__ import annotations

import ast
import copy
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Tool-call argument normalizer ────────────────────────────────────────────


def normalize_tool_call_arguments(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize tool_call argument JSON for bit-stable message prefixes.

    Walks the message list and re-serializes every ``function.arguments``
    JSON string inside ``tool_calls`` blocks with ``sort_keys=True`` and
    compact separators (``,`` / ``:``, no spaces).

    This ensures deterministic argument strings regardless of provider-specific
    key ordering or formatting (OpenAI returns valid JSON; Anthropic SDK
    returns Python ``str()`` repr with single quotes). Deterministic arguments
    maximize prompt cache hit rates by producing bit-identical message prefixes
    across turns.

    Non-decodable argument strings are silently skipped (left unchanged).
    The original message list is not mutated — a deep copy is returned.
    """
    result = copy.deepcopy(messages)

    for msg in result:
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue

        for tc in tool_calls:
            func = tc.get("function")
            if not func:
                continue

            raw = func.get("arguments", "")
            if not raw or not raw.strip():
                continue

            normalized = _normalize_json_string(raw)
            if normalized is not None and normalized != raw:
                func["arguments"] = normalized

    return result


def _normalize_json_string(raw: str) -> str | None:
    """Parse *raw* as JSON (or Python repr) and re-serialize with sort_keys.

    Returns ``None`` if the string can't be parsed, or if ``ast.literal_eval``
    produced a non-dict value (scalar/list). Silently skipped in both cases.
    """
    # Try standard JSON first (OpenAI, OpenRouter, etc.)
    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    except json.JSONDecodeError:
        pass

    # Try Python ast.literal_eval (Anthropic SDK returns str(block.input))
    # This handles single-quoted keys, True/False/None, etc.
    # Guard: only re-serialize dicts (not scalars/lists), and protect
    # against NaN/Infinity that json.dumps would serialise as invalid JSON.
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, dict):
            normalized = json.dumps(
                parsed, sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
            return normalized
    except (ValueError, SyntaxError, MemoryError, TypeError):
        pass

    return None


class AnthropicCachingAdapter:
    """Wraps LLM provider calls to inject cache_control breakpoints.

    Usage:
        caching_adapter = AnthropicCachingAdapter(enabled=True)
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
        If enabled:
        1. Normalizes tool_call argument JSON for bit-stable prefixes
        2. Adds ``cache_control: {"type": "ephemeral"}`` to the last system
           message and the last user message before any assistant response
        """
        if not self._enabled:
            return messages

        # Step 1: Normalize tool_call arguments for bit-stable prefixes
        # (runs before deepcopy so the normalizer does its own copy)
        result = normalize_tool_call_arguments(messages)
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
