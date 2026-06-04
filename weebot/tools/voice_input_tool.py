"""VoiceInputTool — transcribe audio file to text (Enhancement 8).

Requires pip install openai-whisper.  Returns clean error when missing.
"""
from __future__ import annotations

from typing import Any, Optional

from weebot.application.ports.speech_port import SpeechPort
from weebot.tools.base import BaseTool, ToolResult


class VoiceInputTool(BaseTool):
    """Transcribe an audio file to text using Whisper."""

    name: str = "voice_input"
    description: str = (
        "Transcribe an audio file to text using Whisper speech recognition. "
        "Supports wav, mp3, m4a formats. Returns the transcribed text. "
        "Requires: pip install openai-whisper"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "audio_path": {
                "type": "string",
                "description": "Path to audio file (wav, mp3, m4a).",
            },
            "language": {
                "type": "string",
                "description": "Optional language code (e.g., 'en', 'el').",
            },
        },
        "required": ["audio_path"],
    }

    _speech: Optional[SpeechPort] = None

    def __init__(self, speech: Optional[SpeechPort] = None, **data: Any) -> None:
        super().__init__(**data)
        if speech is None:
            from weebot.application.di import Container
            container = Container()
            container.configure_defaults()
            speech = container.get(SpeechPort)
        object.__setattr__(self, "_speech", speech)

    async def execute(self, audio_path: str, language: str = "", **_: Any) -> ToolResult:

        try:
            text = await self._speech.transcribe(
                audio_path, language=language or None
            )
            if not text:
                return ToolResult.success_result(
                    output="(no speech detected)",
                    data={"text": "", "audio_path": audio_path},
                )
            return ToolResult.success_result(
                output=text,
                data={"text": text, "audio_path": audio_path},
            )
        except RuntimeError as exc:
            return ToolResult.error_result(str(exc))
        except Exception as exc:
            return ToolResult.error_result(f"Transcription failed: {exc}")
