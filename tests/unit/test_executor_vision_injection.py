"""Tests for vision-in-the-loop screenshot injection in ExecutorAgent.

Covers the gating (feature flag + model capability) and the image lifecycle
(only the most recent screenshot stays live in the conversation buffer).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from weebot.application.agents.executor._base import ExecutorAgent
from weebot.application.models.tool_collection import ToolCollection
from tests.unit.conftest import VISION_TEST_MODEL

_B64 = "aGVsbG8="


def _make_executor(model: str) -> ExecutorAgent:
    return ExecutorAgent(llm=MagicMock(), tools=ToolCollection(), model=model)


def test_vision_disabled_by_default(monkeypatch):
    # Flag defaults off — even a vision model should not enable injection.
    monkeypatch.setattr(
        "weebot.config.feature_flags.VISION_IN_LOOP_ENABLED", False, raising=False
    )
    ex = _make_executor(VISION_TEST_MODEL)
    assert ex._vision_enabled() is False


def test_vision_enabled_follows_feature_flag_only(monkeypatch):
    """vision_enabled checks feature flag, NOT the current model.

    Model switching to a VLM is handled by _needs_vision + _resolve_model_for_step,
    not by _vision_enabled. So _vision_enabled() should return True whenever the
    feature flag is on, regardless of which model is currently active.
    """
    monkeypatch.setattr(
        "weebot.config.feature_flags.VISION_IN_LOOP_ENABLED", True, raising=False
    )
    # VLM-capable model → enabled
    assert _make_executor(VISION_TEST_MODEL)._vision_enabled() is True
    # Non-vision model → still enabled (switching happens separately)
    assert _make_executor("deepseek-chat")._vision_enabled() is True


def test_inject_keeps_only_latest_screenshot():
    ex = _make_executor(VISION_TEST_MODEL)

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
    ex = _make_executor(VISION_TEST_MODEL)
    ex._conversation_buffer.append({"role": "user", "content": "hello"})

    ex._inject_screenshot("screen_tool", _B64)

    # The plain-string message is untouched; the image message is appended.
    assert ex._conversation_buffer[0] == {"role": "user", "content": "hello"}
    assert isinstance(ex._conversation_buffer[-1]["content"], list)


# ── B2 regression: _inject_screenshot must not mutate original dicts ──────────

def test_inject_screenshot_does_not_mutate_original_dicts():
    ex = _make_executor(VISION_TEST_MODEL)

    original_msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "caption"},
            {"type": "image", "data": _B64, "media_type": "image/png"},
        ],
    }
    ex._conversation_buffer.append(original_msg)

    ex._inject_screenshot("computer_use", "bmV3")

    buf = list(ex._conversation_buffer)
    old_in_buf = buf[0]
    # The dict in the buffer must be a new object
    assert old_in_buf is not original_msg, "original dict must not be reused"
    # The original dict must still have its image block
    assert original_msg["content"][1]["type"] == "image", "original dict was mutated"
    # The buffer entry must have the placeholder
    assert old_in_buf["content"][1]["type"] == "text"
    assert "omitted" in old_in_buf["content"][1]["text"]
