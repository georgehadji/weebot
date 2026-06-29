"""Tests for provider-neutral multimodal message conversion.

Covers the helper that maps neutral image content blocks to Anthropic/OpenAI
wire formats. Plain-string messages (the common case) must pass through untouched.
"""
from __future__ import annotations

import pytest

from weebot.infrastructure.adapters.llm._multimodal import (
    build_image_message,
    convert_messages,
    model_supports_vision,
)
from tests.unit.conftest import VISION_TEST_MODEL

_B64 = "aGVsbG8="  # "hello"


def test_string_content_passes_through_unchanged_for_both_targets():
    # Arrange
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "What is on screen?"},
    ]

    # Act / Assert — neither target should alter plain-string messages
    assert convert_messages(messages, "anthropic") == messages
    assert convert_messages(messages, "openai") == messages


def test_image_block_maps_to_anthropic_source_shape():
    # Arrange
    messages = [build_image_message("current screen:", _B64, "image/png")]

    # Act
    out = convert_messages(messages, "anthropic")

    # Assert
    content = out[0]["content"]
    assert content[0] == {"type": "text", "text": "current screen:"}
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": _B64},
    }


def test_image_block_maps_to_openai_data_url_shape():
    # Arrange
    messages = [build_image_message("current screen:", _B64, "image/png")]

    # Act
    out = convert_messages(messages, "openai")

    # Assert
    content = out[0]["content"]
    assert content[0] == {"type": "text", "text": "current screen:"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{_B64}"},
    }


def test_mixed_block_order_is_preserved():
    # Arrange
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "before"},
                {"type": "image", "data": _B64, "media_type": "image/jpeg"},
                {"type": "text", "text": "after"},
            ],
        }
    ]

    # Act
    out = convert_messages(messages, "anthropic")

    # Assert
    types = [b.get("type") for b in out[0]["content"]]
    assert types == ["text", "image", "text"]
    assert out[0]["content"][1]["source"]["media_type"] == "image/jpeg"


def test_unknown_block_degrades_to_text_without_raising():
    # Arrange
    messages = [{"role": "user", "content": [{"type": "audio", "data": "x"}]}]

    # Act
    out = convert_messages(messages, "openai")

    # Assert
    assert out[0]["content"][0]["type"] == "text"
    assert "audio" in out[0]["content"][0]["text"]


def test_build_image_message_omits_empty_text():
    # Act
    msg = build_image_message("", _B64)

    # Assert — no empty text block, just the image
    assert len(msg["content"]) == 1
    assert msg["content"][0]["type"] == "image"
    assert msg["role"] == "user"


@pytest.mark.parametrize(
    "model",
    [VISION_TEST_MODEL, "claude-sonnet-4-6", "claude-3-5-sonnet", "gpt-4o", "o3-mini", "gpt-4.1"],
)
def test_model_supports_vision_true_for_known_families(model):
    assert model_supports_vision(model) is True


@pytest.mark.parametrize("model", ["deepseek-chat", "gpt-4", "", "text-davinci-003", None])
def test_model_supports_vision_false_for_text_only_or_unknown(model):
    assert model_supports_vision(model) is False


def test_convert_does_not_mutate_input():
    # Arrange
    messages = [build_image_message("x", _B64)]
    original_block = dict(messages[0]["content"][1])

    # Act
    convert_messages(messages, "anthropic")

    # Assert — input list untouched (neutral shape preserved for the other adapter)
    assert messages[0]["content"][1] == original_block


# ── B3 regression: short markers must not false-positive inside longer tokens ─

@pytest.mark.parametrize("model", [
    "openai/o1",
    "o1-mini",
    "o1-preview",
    "openai/o3-mini",
    "o3",
])
def test_o1_o3_match_as_exact_segments(model):
    assert model_supports_vision(model) is True


@pytest.mark.parametrize("model", [
    "vendor/coral-o1dering",   # "o1" inside a longer token
    "provider/tool3-engine",   # no "o3" segment
    "gpto1-variant",           # "o1" not at segment boundary
])
def test_o1_o3_do_not_false_positive_on_substrings(model):
    assert model_supports_vision(model) is False
