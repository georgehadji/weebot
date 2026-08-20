"""Regression tests for buffer sizing and tool/assistant pairing (audit 8.1).

Two independent defects shared one root cause -- a conversation buffer sized
without reference to the tool budget it has to hold:

* the anchoring context message (goal, plan summary, step description) was
  evicted mid-step, so the model lost the step it was executing;
* eviction from the left split assistant/tool pairs, producing orphaned
  ``role="tool"`` messages. That is a provider 400, not a degraded response.

See tasks/specs/side_constraint_integrity_plan.md 8.1.
"""
from __future__ import annotations

from collections import deque

from weebot.application.agents.executor._base import sanitize_tool_call_pairing
from weebot.application.agents.executor._iteration_guard import (
    DEFAULT_MAX_CONTEXT_TURNS,
    _MAX_TOOL_CALLS_PER_STEP,
)


def _assistant(*ids: str, content: str = "calling"):
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [{"id": i, "function": {"name": "x"}} for i in ids],
    }


def _tool(call_id: str):
    return {"role": "tool", "content": "result", "tool_call_id": call_id}


class TestBufferSizing:
    def test_window_holds_a_full_tool_budget(self):
        """1 anchor + 2 messages per tool call must all fit."""
        required = 1 + 2 * _MAX_TOOL_CALLS_PER_STEP
        assert DEFAULT_MAX_CONTEXT_TURNS >= required

    def test_anchor_survives_a_full_budget_of_tool_calls(self):
        """The old maxlen=15 dropped the step description after ~7 calls."""
        buf: deque[dict] = deque(maxlen=DEFAULT_MAX_CONTEXT_TURNS)
        buf.append({"role": "user", "content": "ANCHOR: current step to execute"})
        for i in range(_MAX_TOOL_CALLS_PER_STEP):
            buf.append(_assistant(f"c{i}"))
            buf.append(_tool(f"c{i}"))

        assert any("ANCHOR" in str(m.get("content", "")) for m in buf)

    def test_old_size_would_have_failed(self):
        """Pins why the constant is derived rather than hand-picked."""
        buf: deque[dict] = deque(maxlen=15)
        buf.append({"role": "user", "content": "ANCHOR: current step to execute"})
        for i in range(_MAX_TOOL_CALLS_PER_STEP):
            buf.append(_assistant(f"c{i}"))
            buf.append(_tool(f"c{i}"))

        assert not any("ANCHOR" in str(m.get("content", "")) for m in buf)


class TestSanitizeToolCallPairing:
    def test_wellformed_conversation_is_unchanged(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "go"},
            _assistant("c1"),
            _tool("c1"),
        ]
        assert sanitize_tool_call_pairing(messages) == messages

    def test_orphan_tool_message_is_dropped(self):
        """The eviction case: parent assistant turn fell out of the window."""
        messages = [
            {"role": "system", "content": "sys"},
            _tool("c0"),  # parent gone
            _assistant("c1"),
            _tool("c1"),
        ]
        out = sanitize_tool_call_pairing(messages)
        assert _tool("c0") not in out
        assert len(out) == 3

    def test_unanswered_tool_call_is_stripped_from_assistant(self):
        """The compression case: the reply was rewritten away."""
        messages = [_assistant("c1", "c2"), _tool("c1")]
        out = sanitize_tool_call_pairing(messages)
        assert [tc["id"] for tc in out[0]["tool_calls"]] == ["c1"]

    def test_assistant_with_no_answered_calls_keeps_prose_loses_tool_calls(self):
        messages = [_assistant("c1", content="thinking out loud")]
        out = sanitize_tool_call_pairing(messages)
        assert "tool_calls" not in out[0]
        assert out[0]["content"] == "thinking out loud"

    def test_input_is_not_mutated(self):
        messages = [_assistant("c1", "c2"), _tool("c1")]
        before = [dict(m) for m in messages]
        sanitize_tool_call_pairing(messages)
        assert messages == before

    def test_empty_and_plain_conversations_pass_through(self):
        assert sanitize_tool_call_pairing([]) == []
        plain = [{"role": "user", "content": "hi"}]
        assert sanitize_tool_call_pairing(plain) == plain

    def test_survives_a_left_evicted_window(self):
        """End to end: build a real overflowing buffer, assert it is valid."""
        buf: deque[dict] = deque(maxlen=8)
        for i in range(_MAX_TOOL_CALLS_PER_STEP):
            buf.append(_assistant(f"c{i}"))
            buf.append(_tool(f"c{i}"))

        out = sanitize_tool_call_pairing([{"role": "system", "content": "s"}] + list(buf))

        offered = {
            tc["id"]
            for m in out
            if m.get("role") == "assistant"
            for tc in m.get("tool_calls", [])
        }
        answered = {m["tool_call_id"] for m in out if m.get("role") == "tool"}
        assert answered == offered, "every tool reply must have its parent call"
