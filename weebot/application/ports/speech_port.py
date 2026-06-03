"""SpeechPort — text-to-speech and speech-to-text interface (Enhancement 8).

Optional dependency: pip install weebot[speech] (installs openai-whisper + pyttsx3).
All implementations return clean errors when deps are missing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class SpeechPort(ABC):
    """Convert between speech and text."""

    @abstractmethod
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_path: Path to audio file (wav, mp3, etc.).
            language: Optional ISO 639-1 language code.

        Returns:
            Transcribed text.

        Raises:
            RuntimeError: If speech dependencies are not installed.
        """
        ...

    @abstractmethod
    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        """Synthesize text to speech audio.

        Args:
            text: Text to speak.
            voice: Optional voice identifier.

        Returns:
            WAV audio bytes.

        Raises:
            RuntimeError: If speech dependencies are not installed.
        """
        ...
