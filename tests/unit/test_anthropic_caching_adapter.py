"""Unit tests for AnthropicCachingAdapter — tool-call JSON normalizer."""
from __future__ import annotations

import pytest

from weebot.infrastructure.adapters.llm.anthropic_caching_adapter import (
    AnthropicCachingAdapter,
    normalize_tool_call_arguments,
    _normalize_json_string,
)


# ── _normalize_json_string ───────────────────────────────────────────────────

class TestNormalizeJsonString:
    def test_valid_json_sorted_keys(self):
        """JSON with unsorted keys is re-serialized with sort_keys=True."""
        raw = '{"z": 1, "a": 2, "m": 3}'
        result = _normalize_json_string(raw)
        assert result == '{"a":2,"m":3,"z":1}'

    def test_valid_json_compact_separators(self):
        """Spaces after separators are removed."""
        raw = '{"name": "test", "value": 42}'
        result = _normalize_json_string(raw)
        assert result == '{"name":"test","value":42}'

    def test_valid_json_nested(self):
        """Nested dicts are also sorted."""
        raw = '{"outer": {"z": 1, "a": 2}, "b": 3}'
        result = _normalize_json_string(raw)
        assert result == '{"b":3,"outer":{"a":2,"z":1}}'

    def test_valid_json_array(self):
        """Array values are preserved without reordering."""
        raw = '{"items": [3, 1, 2], "name": "test"}'
        result = _normalize_json_string(raw)
        # Arrays are not sorted, keys are
        assert result == '{"items":[3,1,2],"name":"test"}'

    def test_python_repr_single_quotes(self):
        """Python repr format (Anthropic SDK) with single quotes is parsed."""
        raw = "{'name': 'test', 'value': 42}"
        result = _normalize_json_string(raw)
        assert result == '{"name":"test","value":42}'

    def test_python_repr_boolean_none(self):
        """Python True/False/None repr is converted to JSON booleans/null."""
        raw = "{'active': True, 'count': None, 'flag': False}"
        result = _normalize_json_string(raw)
        assert result == '{"active":true,"count":null,"flag":false}'

    def test_already_normalized_json(self):
        """Already-sorted compact JSON is returned unchanged."""
        raw = '{"a":1,"b":2}'
        result = _normalize_json_string(raw)
        assert result == raw

    def test_invalid_string_returns_none(self):
        """Non-decodable strings return None (silently skipped)."""
        assert _normalize_json_string("not even close") is None
        assert _normalize_json_string("") is None
        assert _normalize_json_string("   ") is None

    def test_str_value_with_escaped_quotes(self):
        """JSON with escaped special chars is parsed correctly."""
        raw = '{"msg": "line1\\nline2"}'
        result = _normalize_json_string(raw)
        assert result is not None
        assert "line1" in result

    def test_empty_dict(self):
        """Empty dict normalizes to '{}'."""
        result = _normalize_json_string("{}")
        assert result == "{}"


# ── normalize_tool_call_arguments ────────────────────────────────────────────

class TestNormalizeToolCallArguments:
    def test_single_tool_call(self):
        """Single tool_call with unsorted arguments."""
        messages = [
            {
                "role": "assistant",
                "content": "Let me search.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "hello", "max_results": 5}',
                        },
                    }
                ],
            }
        ]
        result = normalize_tool_call_arguments(messages)
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert args == '{"max_results":5,"query":"hello"}'

    def test_multiple_tool_calls(self):
        """Multiple tool_calls in one message are all normalized."""
        messages = [
            {
                "role": "assistant",
                "content": "Searching...",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search",
                            "arguments": '{"z": 1, "a": 2}',
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp", "max": 10}',
                        },
                    },
                ],
            }
        ]
        result = normalize_tool_call_arguments(messages)
        tc1_args = result[0]["tool_calls"][0]["function"]["arguments"]
        tc2_args = result[0]["tool_calls"][1]["function"]["arguments"]
        assert tc1_args == '{"a":2,"z":1}'
        assert tc2_args == '{"max":10,"path":"/tmp"}'

    def test_python_repr_arguments(self):
        """Anthropic-style Python repr arguments are normalized."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "toolu_123",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": "{'cmd': 'ls -la', 'timeout': 30}",
                        },
                    }
                ],
            }
        ]
        result = normalize_tool_call_arguments(messages)
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert args == '{"cmd":"ls -la","timeout":30}'

    def test_no_tool_calls_unchanged(self):
        """Messages without tool_calls are not modified."""
        messages = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "Hello!"},
        ]
        result = normalize_tool_call_arguments(messages)
        assert result == messages

    def test_already_normalized_unchanged(self):
        """Messages with already-normalized arguments are unchanged."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "test",
                            "arguments": '{"a":1,"b":2}',
                        },
                    }
                ],
            }
        ]
        result = normalize_tool_call_arguments(messages)
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert args == '{"a":1,"b":2}'

    def test_original_not_mutated(self):
        """The caller's original message list must not be mutated."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "test",
                            "arguments": '{"z": 1, "a": 2}',
                        },
                    }
                ],
            }
        ]
        normalize_tool_call_arguments(messages)
        # Original should still have unsorted, space-y args
        original_args = messages[0]["tool_calls"][0]["function"]["arguments"]
        assert original_args == '{"z": 1, "a": 2}'

    def test_non_decodable_arguments_skipped(self):
        """Non-decodable argument strings are passed through unchanged."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "test",
                            "arguments": "not-json-at-all",
                        },
                    }
                ],
            }
        ]
        result = normalize_tool_call_arguments(messages)
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert args == "not-json-at-all"

    def test_empty_arguments_skipped(self):
        """Empty or whitespace-only argument strings are passed through."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "test",
                            "arguments": "",
                        },
                    }
                ],
            }
        ]
        result = normalize_tool_call_arguments(messages)
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        assert args == ""

    def test_message_with_tool_role_not_affected(self):
        """Tool result messages (role='tool') have no tool_calls and are unchanged."""
        messages = [
            {"role": "tool", "content": "result data", "tool_call_id": "call_1"},
            {"role": "user", "content": "Thanks."},
        ]
        result = normalize_tool_call_arguments(messages)
        assert result == messages


# ── Integration: normalizer inside prepare_messages ──────────────────────────

class TestPrepareMessagesWithNormalizer:
    """Verifies that prepare_messages calls the normalizer when enabled."""

    def _make_messages_with_tool_call(self):
        return [
            {"role": "system", "content": "You are a helpful bot."},
            {"role": "user", "content": "Search for something."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "hello", "max_results": 5}',
                        },
                    }
                ],
            },
            {"role": "tool", "content": "search results", "tool_call_id": "call_1"},
        ]

    def test_normalizer_runs_when_enabled(self):
        """When enabled, prepare_messages normalizes tool_call arguments."""
        adapter = AnthropicCachingAdapter(enabled=True)
        messages = self._make_messages_with_tool_call()
        result = adapter.prepare_messages(messages)

        args = result[2]["tool_calls"][0]["function"]["arguments"]
        assert args == '{"max_results":5,"query":"hello"}'

    def test_normalizer_skipped_when_disabled(self):
        """When disabled, prepare_messages returns messages unchanged."""
        adapter = AnthropicCachingAdapter(enabled=False)
        messages = self._make_messages_with_tool_call()
        result = adapter.prepare_messages(messages)

        args = result[2]["tool_calls"][0]["function"]["arguments"]
        assert args == '{"query": "hello", "max_results": 5}'

    def test_cache_control_still_injected_after_normalizer(self):
        """Cache_control breakpoints are still injected after normalization."""
        adapter = AnthropicCachingAdapter(enabled=True)
        messages = self._make_messages_with_tool_call()
        result = adapter.prepare_messages(messages)

        # System message should get cache_control
        assert result[0].get("cache_control") == {"type": "ephemeral"}
        # User message (before first assistant) should get cache_control
        assert result[1].get("cache_control") == {"type": "ephemeral"}
