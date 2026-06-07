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
from typing import Any, Dict, List, Optional

from .openai_adapter import OpenAIAdapter
from weebot.application.ports.llm_port import LLMResponse
from weebot.config.api_endpoints import DEEPSEEK_API_BASE

_log = logging.getLogger(__name__)


class DeepSeekAdapter(OpenAIAdapter):
    """Adapter for DeepSeek API (OpenAI-compatible) with thinking mode.

    Enables thinking mode by default for DeepSeek V4 Pro via
    ``extra_body={"thinking": {"type": "enabled"}}`` and
    ``reasoning_effort="high"``.  Temperature is omitted (thinking
    mode ignores it anyway).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "deepseek-v4-pro",
    ):
        key = api_key or os.getenv("DEEPSEEK_API_KEY") or "no-key"
        super().__init__(
            api_key=key,
            base_url=DEEPSEEK_API_BASE,
            default_model=default_model,
        )

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Override chat to enable thinking mode for DeepSeek V4 Pro.

        Per https://api-docs.deepseek.com/guides/thinking_mode:
        - Thinking is enabled by default for deepseek-v4-pro
        - Temperature is silently ignored in thinking mode
        - ``reasoning_effort="high"`` for complex agent tasks
        - Tool-call turns must pass ``reasoning_content`` back in context
        """
        return await super().chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            model=model,
            temperature=None,  # thinking mode ignores temperature
            max_tokens=max_tokens,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
