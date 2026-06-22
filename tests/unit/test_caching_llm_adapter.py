"""Unit tests for CachingLLMAdapter and supports_prompt_caching."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.infrastructure.adapters.llm.caching_llm_adapter import (
    CachingLLMAdapter,
    supports_prompt_caching,
    _CACHING_MODEL_MARKERS,
)
from weebot.domain.models.llm_response import LLMResponse


# ── supports_prompt_caching ──────────────────────────────────────────────────

class TestSupportsPromptCaching:
    @pytest.mark.parametrize("model,expected", [
        # Positive matches (should return True)
        ("claude-3-5-haiku", True),
        ("claude-3-5-sonnet", True),
        ("claude-3-opus", True),
        ("claude-4-sonnet", True),
        ("claude-4-opus", True),
        ("anthropic/claude-3-5-sonnet", True),
        ("anthropic/claude-4-sonnet-20250514", True),
        ("claude-3-5-sonnet-20241022", True),
        # Negative matches (should return False)
        ("claude-3-haiku", False),       # v3, not 3.5 — no prompt caching
        ("claude-3-sonnet", False),       # v3, not 3.5
        ("gpt-4o", False),
        ("gpt-4.1", False),
        ("deepseek-v4-flash", False),
        ("", False),
        (None, False),
        ("some-random-model", False),
    ])
    def test_supports_prompt_caching(self, model, expected):
        if model is None:
            result = supports_prompt_caching("")
        else:
            result = supports_prompt_caching(model)
        assert result is expected, (
            f"supports_prompt_caching({model!r}) should be {expected}, got {result}"
        )

    def test_markers_are_nonempty(self):
        """CACHING_MODEL_MARKERS must contain at least one marker."""
        assert len(_CACHING_MODEL_MARKERS) > 0
        for marker in _CACHING_MODEL_MARKERS:
            assert isinstance(marker, str) and len(marker) > 0

    def test_markers_are_lowercase(self):
        """All markers must be lowercase (matching normalizes to lowercase)."""
        for marker in _CACHING_MODEL_MARKERS:
            assert marker == marker.lower(), f"Marker {marker!r} is not lowercase"


# ── CachingLLMAdapter ────────────────────────────────────────────────────────

class TestCachingLLMAdapter:
    """Tests for CachingLLMAdapter chat() delegation with caching."""

    @pytest.fixture
    def mock_inner(self):
        inner = MagicMock()
        inner.chat = AsyncMock(return_value=LLMResponse(
            content="test response",
            tool_calls=None,
            model="claude-3-5-sonnet",
            usage={"input_tokens": 500, "output_tokens": 100, "total_tokens": 600},
        ))
        return inner

    @pytest.fixture
    def sample_messages(self):
        return [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]

    @pytest.mark.asyncio
    async def test_chat_passthrough_when_disabled(self, mock_inner, sample_messages):
        """When enabled=False, messages pass through without modification."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=False,
        )

        result = await adapter.chat(messages=sample_messages)
        assert result.content == "test response"

        # Inner adapter received the exact same message list (no cache control)
        _, kwargs = mock_inner.chat.await_args
        assert kwargs["messages"] == sample_messages

    @pytest.mark.asyncio
    async def test_caching_injected_for_supported_model(self, mock_inner, sample_messages):
        """When enabled=True and model supports caching, cache_control is injected."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="anthropic/claude-3-5-sonnet",
            enabled=True,
        )

        result = await adapter.chat(messages=sample_messages)
        assert result is not None

        # Inner adapter received modified messages with cache_control
        _, kwargs = mock_inner.chat.await_args
        modified = kwargs["messages"]
        found_cache = any(
            msg.get("cache_control") == {"type": "ephemeral"}
            for msg in modified
        )
        assert found_cache, "Expected at least one message with cache_control"

    @pytest.mark.asyncio
    async def test_caching_not_injected_for_unsupported_model(self, mock_inner, sample_messages):
        """When enabled=True but model doesn't support caching, messages pass through."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="gpt-4o",
            enabled=True,
        )

        result = await adapter.chat(messages=sample_messages)
        assert result.content == "test response"

        # Inner adapter received unmodified messages
        _, kwargs = mock_inner.chat.await_args
        assert kwargs["messages"] == sample_messages

    @pytest.mark.asyncio
    async def test_chat_passthrough_kwargs(self, mock_inner, sample_messages):
        """All keyword arguments are forwarded to the inner adapter unchanged."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=False,
        )

        await adapter.chat(
            messages=sample_messages,
            tools=[{"type": "function", "function": {"name": "test"}}],
            tool_choice="auto",
            temperature=0.7,
            max_tokens=1000,
        )

        _, kwargs = mock_inner.chat.await_args
        assert kwargs["tools"] == [{"type": "function", "function": {"name": "test"}}]
        assert kwargs["tool_choice"] == "auto"
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_cache_telemetry_low_input_warning(self, mock_inner, sample_messages, caplog):
        """When input tokens are very low, a WARN is emitted for cache-miss telemetry."""
        # Override mock to return very low input token count
        mock_inner.chat = AsyncMock(return_value=LLMResponse(
            content="short response",
            tool_calls=None,
            model="claude-3-5-sonnet",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ))

        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=True,
        )

        import logging
        with caplog.at_level(logging.WARNING):
            await adapter.chat(messages=sample_messages)

        assert "CachingLLMAdapter" in caplog.text
        assert "unusually low input token count" in caplog.text

    @pytest.mark.asyncio
    async def test_cache_telemetry_no_warning_for_normal_input(self, mock_inner, sample_messages, caplog):
        """With normal input token counts, no WARN is emitted."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=True,
        )

        import logging
        with caplog.at_level(logging.WARNING):
            await adapter.chat(messages=sample_messages)

        assert "unusually low input token count" not in caplog.text

    @pytest.mark.asyncio
    async def test_cache_telemetry_no_warning_when_disabled(self, mock_inner, sample_messages, caplog):
        """When caching is disabled, no cache telemetry happens regardless of input tokens."""
        mock_inner.chat = AsyncMock(return_value=LLMResponse(
            content="short",
            tool_calls=None,
            model="claude-3-5-sonnet",
            usage={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        ))

        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=False,
        )

        import logging
        with caplog.at_level(logging.WARNING):
            await adapter.chat(messages=sample_messages)

        assert "unusually low input token count" not in caplog.text

    @pytest.mark.asyncio
    async def test_model_override_suppresses_caching_for_non_anthropic(self, mock_inner, sample_messages):
        """When chat(model=...) overrides to a non-caching model, cache injection is skipped."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",  # constructor: caching model
            enabled=True,
        )

        await adapter.chat(messages=sample_messages, model="gpt-4o")  # override: non-caching

        _, kwargs = mock_inner.chat.await_args
        assert kwargs["model"] == "gpt-4o"
        # Messages should be unmodified (no cache_control)
        assert kwargs["messages"] == sample_messages, (
            "Messages should not be modified when the override model doesn't support caching"
        )

    @pytest.mark.asyncio
    async def test_model_override_enables_caching_for_anthropic(self, mock_inner, sample_messages):
        """When chat(model=...) overrides to a caching model, cache injection fires."""
        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="gpt-4o",  # constructor: non-caching model
            enabled=True,
        )

        await adapter.chat(messages=sample_messages, model="anthropic/claude-4-sonnet")

        _, kwargs = mock_inner.chat.await_args
        assert kwargs["model"] == "anthropic/claude-4-sonnet"
        modified = kwargs["messages"]
        found_cache = any(
            msg.get("cache_control") == {"type": "ephemeral"}
            for msg in modified
        )
        assert found_cache, (
            "Cache breakpoints should be injected when the override model supports caching"
        )

    @pytest.mark.asyncio
    async def test_original_messages_not_mutated(self, mock_inner, sample_messages):
        """The wrapper must not mutate the caller's message list."""
        original_messages = sample_messages.copy()

        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=True,
        )

        await adapter.chat(messages=sample_messages)

        # Verify original messages haven't been mutated
        for i, msg in enumerate(original_messages):
            assert msg.get("cache_control") is None, (
                f"Original message {i} was mutated with cache_control"
            )


# ── Integration with AnthropicCachingAdapter ─────────────────────────────────

class TestCachingLLMAdapterIntegration:
    """Verifies CachingLLMAdapter + AnthropicCachingAdapter work together."""

    @pytest.mark.asyncio
    async def test_cache_control_on_system_and_conversation_user_message(self):
        """With a multi-turn conversation, cache_control is set on system and last user message.

        The AnthropicCachingAdapter only caches a user message when it appears
        before an assistant response (i.e., in a multi-turn conversation).
        """
        mock_inner = MagicMock()
        mock_inner.chat = AsyncMock(return_value=LLMResponse(
            content="ok",
            tool_calls=None,
            model="claude-3-5-sonnet",
            usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        ))

        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=True,
        )

        # Multi-turn conversation: system, user, assistant, user
        # The second user message (before no assistant) should get cache_control
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "Paris."},
            {"role": "user", "content": "What about Germany?"},
        ]

        await adapter.chat(messages=messages)

        _, kwargs = mock_inner.chat.await_args
        modified = kwargs["messages"]

        # System message should have cache_control
        assert modified[0].get("cache_control") == {"type": "ephemeral"}, (
            "System message should have cache_control"
        )
        # Last user message (before the first assistant) should have cache_control
        assert modified[1].get("cache_control") == {"type": "ephemeral"}, (
            "Last user message before assistant response should have cache_control"
        )

    @pytest.mark.asyncio
    async def test_no_cache_control_when_disabled(self):
        """When caching is disabled, no cache_control is set."""
        mock_inner = MagicMock()
        mock_inner.chat = AsyncMock(return_value=LLMResponse(
            content="ok",
            tool_calls=None,
            model="claude-3-5-sonnet",
            usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        ))

        adapter = CachingLLMAdapter(
            inner_adapter=mock_inner,
            model="claude-3-5-sonnet",
            enabled=False,
        )

        messages = [
            {"role": "system", "content": "System instruction."},
            {"role": "user", "content": "Hello."},
        ]

        await adapter.chat(messages=messages)

        _, kwargs = mock_inner.chat.await_args
        modified = kwargs["messages"]
        for msg in modified:
            assert "cache_control" not in msg, (
                f"Message should not have cache_control when disabled: {msg}"
            )
