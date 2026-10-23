"""DeepSeek LLM adapter — OpenAI-compatible with DeepSeek base URL.

DeepSeek V4 Pro thinking mode (enabled by default):
- Does NOT support temperature, top_p, presence_penalty, frequency_penalty
- Uses ``extra_body={"thinking": {"type": "enabled"}}`` via OpenAI SDK
- ``reasoning_effort="high"`` for complex agent tasks
- ``reasoning_content`` must be passed back in context for tool-call turns

Ref: https://api-docs.deepseek.com/guides/thinking_mode
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .openai_adapter import OpenAIAdapter
from weebot.application.ports.llm_port import LLMResponse
from weebot.config.api_endpoints import DEEPSEEK_API_BASE
from weebot.config.model_refs import MODEL_FACTORY_DEEPSEEK as _MODEL_FACTORY_DEEPSEEK

# Strip provider prefix for direct API: "deepseek/deepseek-v4-pro" → "deepseek-v4-pro"
_MODEL_FACTORY_DEEPSEEK_STRIPPED = (
    _MODEL_FACTORY_DEEPSEEK.split("/", 1)[-1]
    if "/" in _MODEL_FACTORY_DEEPSEEK
    else _MODEL_FACTORY_DEEPSEEK
)
del _MODEL_FACTORY_DEEPSEEK
MODEL_FACTORY_DEEPSEEK_STRIPPED = _MODEL_FACTORY_DEEPSEEK_STRIPPED

_log = logging.getLogger(__name__)


def native_model_id(model: str) -> str:
    """The DeepSeek API id for an OpenRouter-style DeepSeek id.

    The API serves only the aliases ``deepseek-flash`` and ``deepseek-v4-pro``
    and rejects versioned ids such as ``deepseek-v4.1-flash`` with 400.
    """
    name = model.split("/", 1)[-1].split(":", 1)[0].lower()
    return "deepseek-v4-pro" if "pro" in name else "deepseek-flash"


class DeepSeekAdapter(OpenAIAdapter):
    """Adapter for DeepSeek API (OpenAI-compatible) with thinking mode.

    Enables thinking mode by default for DeepSeek V4 Pro via
    ``extra_body={"thinking": {"type": "enabled"}}`` and
    ``reasoning_effort="high"``.  Temperature is omitted (thinking
    mode ignores it anyway).
    """

    def __init__(
        self, api_key: str | None = None, default_model: str = MODEL_FACTORY_DEEPSEEK_STRIPPED
    ):
        key = api_key or os.getenv("DEEPSEEK_API_KEY") or "no-key"
        super().__init__(api_key=key, base_url=DEEPSEEK_API_BASE, default_model=default_model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """Think only when the caller asks for a reasoning effort.

        Per https://api-docs.deepseek.com/guides/thinking_mode thinking is on by
        default. Forcing it at "high" on every call made a planning call 3.8 s
        against 1.4 s without (2026-10-23), so it is off unless requested.
        """
        thinking = reasoning_effort not in (None, "none", "minimal")
        return await super().chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            model=native_model_id(model or self._default_model),
            temperature=None if thinking else temperature,  # thinking ignores it
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort if thinking else None,
            extra_body={
                **(extra_body or {}),
                "thinking": {"type": "enabled" if thinking else "disabled"},
            },
        )
