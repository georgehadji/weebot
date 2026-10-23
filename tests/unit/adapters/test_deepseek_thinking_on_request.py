"""DeepSeek-direct thinks only when the caller asks for it.

Measured 2026-10-23 on a planning-sized prompt: the adapter forced
reasoning_effort="high" plus thinking on every call, 3.8 s median, against
1.4 s with thinking disabled and 2.6 s through OpenRouter. Planning median
rose from 2.4 s to 3.8 s once DeepSeek-direct was funded.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.llm_response import LLMResponse
from weebot.infrastructure.adapters.llm.deepseek_adapter import DeepSeekAdapter


@pytest.fixture
def sent(monkeypatch):
    calls = {}

    async def _chat(self, **kw):
        calls.update(kw)
        return LLMResponse(content="ok", tool_calls=None, usage=None)

    monkeypatch.setattr(
        "weebot.infrastructure.adapters.llm.openai_adapter.OpenAIAdapter.chat", _chat
    )
    return calls


@pytest.mark.asyncio
async def test_no_effort_requested_means_no_thinking(sent):
    await DeepSeekAdapter(api_key="k").chat(messages=[{"role": "user", "content": "hi"}])
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}
    assert sent.get("reasoning_effort") is None


@pytest.mark.asyncio
async def test_a_requested_effort_turns_thinking_on(sent):
    await DeepSeekAdapter(api_key="k").chat(
        messages=[{"role": "user", "content": "hi"}], reasoning_effort="high"
    )
    assert sent["extra_body"] == {"thinking": {"type": "enabled"}}
    assert sent["reasoning_effort"] == "high"
