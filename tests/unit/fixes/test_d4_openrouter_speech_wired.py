"""D4: WEEBOT_SPEECH_BACKEND=openrouter selects the OpenRouter speech adapter.

The voice tools ran on the Whisper adapter only, whose packages are not in the
requirements, so they could not work on a default install. The OpenRouter adapter
needs only aiohttp but had no caller; it also read its key with a bare `os.getenv`
behind a "no-key" sentinel, and its mp3 audio was saved under a `.wav` name.
"""

import importlib
import sys

import pytest

from weebot.config.secret_accessor import SecretAccessor
from weebot.infrastructure.adapters.speech import openrouter_speech_adapter as module
from weebot.infrastructure.adapters.speech.openrouter_speech_adapter import (
    OpenRouterSpeechAdapter,
)


def _no_http(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr(module.aiohttp, "ClientSession", refuse)


async def test_without_a_key_it_refuses_before_any_request(monkeypatch):
    monkeypatch.setattr(SecretAccessor, "get", staticmethod(lambda *_a, **_k: None))
    _no_http(monkeypatch)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await OpenRouterSpeechAdapter().synthesize("hi")


async def test_the_key_comes_from_the_secret_accessor(monkeypatch):
    seen = {}

    class _Resp:
        status = 200

        async def read(self):
            return b"ID3audio"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def post(self, url, headers, json, timeout):
            seen.update(url=url, auth=headers["Authorization"])
            return _Resp()

    monkeypatch.setattr(
        SecretAccessor, "get", staticmethod(lambda name, *_a, **_k: "k-test" if name else None)
    )
    monkeypatch.setattr(module.aiohttp, "ClientSession", _Session)
    assert await OpenRouterSpeechAdapter().synthesize("hi") == b"ID3audio"
    assert seen["url"].endswith("/audio/speech") and seen["auth"] == "Bearer k-test"


def test_the_backend_flag_selects_the_adapter(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di import Container

    monkeypatch.setenv("WEEBOT_SPEECH_BACKEND", "openrouter")
    importlib.reload(flags)
    try:
        assert isinstance(Container._create_speech(), OpenRouterSpeechAdapter)
    finally:
        monkeypatch.delenv("WEEBOT_SPEECH_BACKEND")
        importlib.reload(flags)
    assert flags.SPEECH_BACKEND == "whisper"


@pytest.mark.skipif(sys.platform not in ("win32", "darwin"), reason="voice output platforms")
async def test_mp3_audio_is_saved_as_mp3(monkeypatch, tmp_path):
    from weebot.tools import voice_output_tool as tool_module
    from weebot.tools.voice_output_tool import VoiceOutputTool

    class _Speech:
        audio_suffix = ".mp3"

        async def synthesize(self, text, voice=None):
            return b"ID3audio"

    monkeypatch.setattr(tool_module, "WORKSPACE_ROOT", tmp_path)
    # The tool writes through write_target (R14); stub it so tmp_path stands in for the project.
    monkeypatch.setattr("weebot.core.output_path.write_target", lambda p, suffixes=None: p)
    result = await VoiceOutputTool(speech=_Speech()).execute(text="hi")
    path = result.data["path"]
    assert path.endswith(".mp3")
    with open(path, "rb") as fh:
        assert fh.read() == b"ID3audio"
