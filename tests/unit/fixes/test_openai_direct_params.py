"""Direct OpenAI calls use max_completion_tokens.

Found on the first funded direct call (2026-10-23): api.openai.com rejects
`max_tokens` for current models ("Use 'max_completion_tokens' instead") with
400. OpenRouter accepts `max_tokens`, so only the direct path broke.
"""

from __future__ import annotations

from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter


def _kwargs(adapter: OpenAIAdapter, model: str) -> dict:
    return adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], model=model, max_tokens=256
    )


def test_direct_openai_sends_max_completion_tokens():
    adapter = OpenAIAdapter(api_key="sk-proj-test", default_model="gpt-6-luna")
    kw = _kwargs(adapter, "gpt-6-luna")
    assert "max_tokens" not in kw
    assert kw["max_completion_tokens"] >= 256


def test_openrouter_keeps_max_tokens():
    adapter = OpenAIAdapter(api_key="sk-or-v1-test", default_model="openai/gpt-6-luna")
    kw = _kwargs(adapter, "openai/gpt-6-luna")
    assert "max_completion_tokens" not in kw
    assert kw["max_tokens"] >= 256


def test_direct_openai_with_tools_turns_reasoning_off():
    # "Function tools with reasoning_effort are not supported for gpt-6-luna in
    # /v1/chat/completions ... set reasoning_effort to 'none'."
    adapter = OpenAIAdapter(api_key="sk-proj-test", default_model="gpt-6-luna")
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    kw = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=tools, model="gpt-6-luna",
        max_tokens=512, reasoning_effort="high",
    )
    assert kw["reasoning_effort"] == "none"


def test_a_mandatory_reasoner_keeps_an_allowed_effort_with_tools():
    # gpt-6.1-sol rejects "none": "Supported values are: 'low', 'medium', 'high'..."
    adapter = OpenAIAdapter(api_key="sk-proj-test", default_model="gpt-6.1-sol")
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    kw = adapter._build_kwargs(
        messages=[{"role": "user", "content": "hi"}], tools=tools, model="gpt-6.1-sol",
        max_tokens=512,
    )
    assert kw.get("reasoning_effort") in ("low", "medium", "high", "xhigh", None)
