"""WhisperSpeechAdapter — whisper STT + pyttsx3 TTS (Enhancement 8).

Optional dependency.  Clean errors when deps are missing.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.speech_port import SpeechPort

logger = logging.getLogger(__name__)

# Lazy imports with friendly error messages
_WHISPER_AVAILABLE = False
_TTS_AVAILABLE = False

try:
    import whisper  # type: ignore
    _WHISPER_AVAILABLE = True
except ImportError:
    whisper = None

try:
    import pyttsx3  # type: ignore
    _TTS_AVAILABLE = True
except ImportError:
    pyttsx3 = None


class WhisperSpeechAdapter(SpeechPort):
    """Whisper transcription + pyttsx3 synthesis adapter."""

    def __init__(self, model_name: str = "base") -> None:
        self._model_name = model_name
        self._whisper_model = None
        self._tts_engine = None

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        if not _WHISPER_AVAILABLE:
            raise RuntimeError(
                "Whisper STT not available. Install: pip install openai-whisper"
            )
        if self._whisper_model is None:
            self._whisper_model = whisper.load_model(self._model_name)

        result = self._whisper_model.transcribe(
            audio_path, language=language or None
        )
        return result.get("text", "").strip()

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        if not _TTS_AVAILABLE:
            raise RuntimeError(
                "TTS not available. Install: pip install pyttsx3"
            )
        import io
        import tempfile

        engine = pyttsx3.init()
        if voice:
            voices = engine.getProperty("voices")
            for v in voices:
                if voice.lower() in v.name.lower():
                    engine.setProperty("voice", v.id)
                    break

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = tmp.name

        engine.save_to_file(text, temp_path)
        engine.runAndWait()

        with open(temp_path, "rb") as f:
            audio_bytes = f.read()

        import os
        os.unlink(temp_path)
        return audio_bytes
