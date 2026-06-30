"""OpenRouterSpeechAdapter — speech STT + TTS using OpenRouter cloud APIs."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp

from weebot.application.ports.speech_port import SpeechPort

logger = logging.getLogger(__name__)


class OpenRouterSpeechAdapter(SpeechPort):
    """Speech transcription (STT) and speech synthesis (TTS) using OpenRouter's API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        tts_model: str = "elevenlabs/eleven-turbo-v2",
        stt_model: str = "openai/whisper-large-v3",
    ) -> None:
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY") or "no-key"
        self._tts_model = tts_model
        self._stt_model = stt_model

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        """Transcribe an audio file using OpenRouter's speech-to-text endpoint."""
        if self._api_key == "no-key":
            raise RuntimeError("OPENROUTER_API_KEY is not set. Get a key at https://openrouter.ai")

        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        import base64
        audio_bytes = path.read_bytes()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        ext = path.suffix.lstrip(".").lower() or "wav"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/weebot",
            "X-Title": "weebot",
        }

        payload: dict = {
            "model": self._stt_model,
            "input_audio": {
                "data": audio_b64,
                "format": ext,
            }
        }
        if language:
            payload["language"] = language

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/audio/transcriptions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise RuntimeError(f"OpenRouter STT failed (HTTP {resp.status}): {err_text[:150]}")
                data = await resp.json()
                return data.get("text", "").strip()

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        """Synthesize text into speech audio bytes using OpenRouter's text-to-speech endpoint."""
        if self._api_key == "no-key":
            raise RuntimeError("OPENROUTER_API_KEY is not set. Get a key at https://openrouter.ai")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/weebot",
            "X-Title": "weebot",
        }

        payload = {
            "model": self._tts_model,
            "input": text,
            "voice": voice or "alloy",
            "response_format": "mp3",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/audio/speech",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise RuntimeError(f"OpenRouter TTS failed (HTTP {resp.status}): {err_text[:150]}")
                return await resp.read()
