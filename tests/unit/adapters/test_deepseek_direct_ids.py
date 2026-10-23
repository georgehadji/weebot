"""DeepSeek-direct sends ids the DeepSeek API accepts.

Found on the first funded call (2026-10-23): the API serves only the aliases
`deepseek-flash` and `deepseek-v4-pro` and rejects the OpenRouter id
`deepseek-v4.1-flash` with 400, so every direct call failed and fell back to
OpenRouter after a wasted round trip.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.llm_response import LLMResponse
from weebot.infrastructure.adapters.llm.deepseek_adapter import DeepSeekAdapter, native_model_id


@pytest.mark.parametrize(
    ("model", "native"),
    [
        ("deepseek-v4.1-flash", "deepseek-flash"),
        ("deepseek/deepseek-v4.1-flash", "deepseek-flash"),
        ("deepseek-v4-flash:thinking", "deepseek-flash"),
        ("deepseek-v4-pro", "deepseek-v4-pro"),
        ("deepseek-v4.1-pro", "deepseek-v4-pro"),
        ("deepseek-flash", "deepseek-flash"),
    ],
)
def test_native_model_id(model, native):
    assert native_model_id(model) == native


@pytest.mark.asyncio
async def test_chat_sends_the_native_id(monkeypatch):
    sent = {}

    async def _chat(self, **kw):
        sent.update(kw)
        return LLMResponse(content="ok", tool_calls=None, usage=None)

    monkeypatch.setattr(
        "weebot.infrastructure.adapters.llm.openai_adapter.OpenAIAdapter.chat", _chat
    )
    adapter = DeepSeekAdapter(api_key="k", default_model="deepseek-v4.1-flash")
    await adapter.chat(messages=[{"role": "user", "content": "hi"}], model="deepseek-v4.1-flash")
    assert sent["model"] == "deepseek-flash"
