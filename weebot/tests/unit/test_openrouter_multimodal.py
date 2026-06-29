"""Unit tests for OpenRouter Multimodal extensions and OpenRouterSpeechAdapter."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from weebot.infrastructure.adapters.llm._multimodal import _convert_blocks, convert_messages
from weebot.infrastructure.adapters.speech.openrouter_speech_adapter import OpenRouterSpeechAdapter


def test_convert_blocks_openrouter_multimodal():
    """Verify that pdf, audio, and video content blocks translate correctly for OpenAI/OpenRouter and Anthropic."""
    neutral_blocks = [
        {"type": "text", "text": "Analyzing multimodal feeds:"},
        {
            "type": "pdf",
            "data": "JVBERi0xLjQK...",
            "filename": "summary.pdf"
        },
        {
            "type": "audio",
            "data": "UklGRiQA...",
            "format": "wav"
        },
        {
            "type": "video",
            "data": "AAAAIGZ0eX...",
            "media_type": "video/mp4"
        }
    ]

    # Test conversion for OpenAI/OpenRouter
    openai_blocks = _convert_blocks(neutral_blocks, "openai")
    assert len(openai_blocks) == 4
    assert openai_blocks[0] == {"type": "text", "text": "Analyzing multimodal feeds:"}
    assert openai_blocks[1] == {
        "type": "file",
        "file": {
            "filename": "summary.pdf",
            "file_data": "data:application/pdf;base64,JVBERi0xLjQK..."
        }
    }
    assert openai_blocks[2] == {
        "type": "input_audio",
        "input_audio": {
            "data": "UklGRiQA...",
            "format": "wav"
        }
    }
    assert openai_blocks[3] == {
        "type": "video_url",
        "video_url": {
            "url": "data:video/mp4;base64,AAAAIGZ0eX..."
        }
    }

    # Test conversion for Anthropic
    anthropic_blocks = _convert_blocks(neutral_blocks, "anthropic")
    assert len(anthropic_blocks) == 4
    assert anthropic_blocks[0] == {"type": "text", "text": "Analyzing multimodal feeds:"}
    assert anthropic_blocks[1] == {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": "JVBERi0xLjQK..."
        }
    }
    assert anthropic_blocks[2]["type"] == "text"  # Degradation for unsupported audio on Anthropic
    assert anthropic_blocks[3]["type"] == "text"  # Degradation for unsupported video on Anthropic


@pytest.mark.asyncio
async def test_openrouter_speech_adapter(tmp_path):
    """Test SpeechPort synthesis and transcription using the OpenRouterSpeechAdapter with mock API calls."""
    adapter = OpenRouterSpeechAdapter(
        api_key="sk-or-v1-testkey",
        tts_model="elevenlabs/eleven-turbo-v2",
        stt_model="openai/whisper-large-v3"
    )

    dummy_audio = tmp_path / "test.wav"
    dummy_audio.write_bytes(b"mock-wav-payload")

    # Mock post requests
    mock_response_stt = AsyncMock()
    mock_response_stt.status = 200
    mock_response_stt.json = AsyncMock(return_value={"text": "Hello world from OpenRouter STT"})

    mock_response_tts = AsyncMock()
    mock_response_tts.status = 200
    mock_response_tts.read = AsyncMock(return_value=b"synthesized-audio-bytes")

    with patch("aiohttp.ClientSession.post") as mock_post:
        # 1. Test transcription (STT)
        mock_post.return_value.__aenter__.return_value = mock_response_stt
        text = await adapter.transcribe(str(dummy_audio), language="en")
        assert text == "Hello world from OpenRouter STT"
        assert mock_post.called

        # 2. Test synthesis (TTS)
        mock_post.return_value.__aenter__.return_value = mock_response_tts
        audio_bytes = await adapter.synthesize("Hello world", voice="alloy")
        assert audio_bytes == b"synthesized-audio-bytes"


def test_zai_multimodal_payload_mapping():
    """Verify that visual and video models (Z.AI) map neutral block types correctly."""
    neutral_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Analyze the action in this video block:"},
                {
                    "type": "video",
                    "data": "AAAAIGZ0eX...",
                    "media_type": "video/mp4"
                }
            ]
        }
    ]

    # Translate messages for Z.AI (OpenAI-compatible) target
    converted = convert_messages(neutral_messages, "openai")
    
    assert len(converted) == 1
    content_blocks = converted[0]["content"]
    assert len(content_blocks) == 2
    assert content_blocks[0] == {"type": "text", "text": "Analyze the action in this video block:"}
    assert content_blocks[1] == {
        "type": "video_url",
        "video_url": {
            "url": "data:video/mp4;base64,AAAAIGZ0eX..."
        }
    }

