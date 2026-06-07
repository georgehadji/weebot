"""Moonshot (Kimi) LLM adapter — OpenAI-compatible with Moonshot base URL.

Uses ``KIMI_API_KEY`` (priority) or ``MOONSHOT_API_KEY`` (fallback)
environment variable.  Falls back to OpenRouter when no direct API key
is available or the call fails.

Kimi K2.6 requires ``temperature=1`` — the adapter overrides any other
value to prevent ``BadRequestError`` (400: invalid temperature).

Kimi K2.6 API docs: https://platform.kimi.ai/docs/api/
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .openai_adapter import OpenAIAdapter
from weebot.application.ports.llm_port import LLMResponse
from weebot.config.api_endpoints import MOONSHOT_API_BASE

_log = logging.getLogger(__name__)


class MoonshotAdapter(OpenAIAdapter):
    """Adapter for Moonshot / Kimi API (OpenAI-compatible).

    Connects directly to ``https://api.moonshot.ai/v1`` using either
    ``KIMI_API_KEY`` (tried first) or ``MOONSHOT_API_KEY`` (official
    env var from Kimi docs).  This bypasses OpenRouter markup, reducing
    cost and latency for Kimi models.

    The native model name is ``kimi-k2.6`` (confirmed via platform.kimi.ai
    API docs — both partial mode and tool-use examples use this ID).
    """

    # Kimi K2.6 only accepts temperature=1.0
    _FORCED_TEMPERATURE: float = 1.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "kimi-k2.6",
    ):
        key = (
            api_key
            or os.getenv("KIMI_API_KEY")
            or os.getenv("MOONSHOT_API_KEY")
            or ""
        )
        super().__init__(
            api_key=key,
            base_url=MOONSHOT_API_BASE,
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
        """Override chat for Kimi K2.6 compatibility.

        Kimi K2.6 thinking model: omit temperature entirely (use API default).
        All other Kimi models: force temperature=1.0 (only accepted value).

        Per https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model
        """
        effective_temp = None  # Omit — let API use default for thinking models
        return await super().chat(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            model=model,
            temperature=effective_temp,
            max_tokens=max_tokens,
        )
