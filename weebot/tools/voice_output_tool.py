"""VoiceOutputTool — synthesize text to speech (Enhancement 8).

Saves audio to a file and returns the path.  Requires pip install pyttsx3.
Returns clean error when missing.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.speech_port import SpeechPort
from weebot.config.settings import WORKSPACE_ROOT
from weebot.tools.base import BaseTool, ToolResult


class VoiceOutputTool(BaseTool):
    """Synthesize text to speech and save to a file."""

    max_concurrent: int = 1
    default_timeout_seconds: int = 30
    name: str = "voice_output"
    description: str = (
        "Convert text to speech and save as a WAV audio file. "
        "Returns the path to the generated file. "
        "Requires: pip install pyttsx3"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to speak.",
            },
            "voice": {
                "type": "string",
                "description": "Optional voice name (e.g., 'Microsoft David').",
            },
            "output_path": {
                "type": "string",
                "description": "Optional output path (default: workspace/<uuid>.wav).",
            },
        },
        "required": ["text"],
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

    async def health_check(self) -> bool:
        """Check if TTS dependencies are available."""
        try:
            import pyttsx3  # noqa: F401
            return True
        except ImportError:
            return False

    async def execute(
        self, text: str, voice: str = "", output_path: str = "", **_: Any
    ) -> ToolResult:
        import sys as _sys
        if _sys.platform == "win32":
            pass  # Windows — pyttsx3 and speech APIs available
        elif _sys.platform == "darwin":
            pass  # macOS — may have NSSpeechSynthesizer
        else:
            return ToolResult(error=f"Voice output not supported on {_sys.platform}", output="")

        if not output_path:
            output_path = str(WORKSPACE_ROOT / f"speech_{uuid.uuid4().hex[:8]}.wav")

        try:
            audio = await self._speech.synthesize(text, voice=voice or None)
            Path(output_path).write_bytes(audio)
            return ToolResult.success_result(
                output=f"Audio saved to {output_path}",
                data={"path": output_path, "bytes": len(audio)},
            )
        except RuntimeError as exc:
            return ToolResult.error_result(str(exc))
        except Exception as exc:
            return ToolResult.error_result(f"Speech synthesis failed: {exc}")
