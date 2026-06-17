"""Tests for vision-in-the-loop screenshot injection in ExecutorAgent.

Covers the gating (feature flag + model capability) and the image lifecycle
(only the most recent screenshot stays live in the conversation buffer).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from weebot.application.agents.executor._base import ExecutorAgent
from weebot.application.models.tool_collection import ToolCollection

_B64 = "aGVsbG8="


def _make_executor(model: str) -> ExecutorAgent:
    return ExecutorAgent(llm=MagicMock(), tools=ToolCollection(), model=model)


def test_vision_disabled_by_default(monkeypatch):
    # Flag defaults off — even a vision model should not enable injection.
    monkeypatch.setattr(
        "weebot.config.feature_flags.VISION_IN_LOOP_ENABLED", False, raising=False
    )
    ex = _make_executor("claude-opus-4-8")
    assert ex._vision_enabled() is False


def test_vision_enabled_requires_capable_model(monkeypatch):
    monkeypatch.setattr(
        "weebot.config.feature_flags.VISION_IN_LOOP_ENABLED", True, raising=False
    )
    assert _make_executor("claude-opus-4-8")._vision_enabled() is True
    assert _make_executor("deepseek-chat")._vision_enabled() is False


def test_inject_keeps_only_latest_screenshot():
    ex = _make_executor("claude-opus-4-8")

    # Act — two screenshots injected in sequence
    ex._inject_screenshot("advanced_browser", _B64)
    ex._inject_screenshot("computer_use", _B64)

    # Assert — exactly one live image block remains; the earlier one is a placeholder
    buf = list(ex._conversation_buffer)
    image_blocks = [
        b
        for msg in buf
        if isinstance(msg.get("content"), list)
        for b in msg["content"]
        if isinstance(b, dict) and b.get("type") == "image"
    ]
    assert len(image_blocks) == 1

    placeholders = [
        b
        for msg in buf
        if isinstance(msg.get("content"), list)
        for b in msg["content"]
        if isinstance(b, dict) and b.get("type") == "text" and "omitted" in b.get("text", "")
    ]
    assert len(placeholders) == 1


def test_inject_does_not_disturb_plain_string_messages():
    ex = _make_executor("claude-opus-4-8")
    ex._conversation_buffer.append({"role": "user", "content": "hello"})

    ex._inject_screenshot("screen_tool", _B64)

    # The plain-string message is untouched; the image message is appended.
    assert ex._conversation_buffer[0] == {"role": "user", "content": "hello"}
    assert isinstance(ex._conversation_buffer[-1]["content"], list)
