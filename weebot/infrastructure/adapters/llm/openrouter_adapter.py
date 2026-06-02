"""OpenRouter LLM adapter — OpenAI-compatible with OpenRouter base URL and headers."""
from __future__ import annotations

import os
from typing import Optional

from openai import AsyncOpenAI

from .openai_adapter import OpenAIAdapter
from weebot.config.api_endpoints import OPENROUTER_API_BASE


class OpenRouterAdapter(OpenAIAdapter):
    """Adapter for OpenRouter (unified API for 350+ models)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "moonshotai/kimi-k2.6",
        http_referer: Optional[str] = None,
        x_title: Optional[str] = None,
    ):
        key = api_key or os.getenv("OPENROUTER_API_KEY") or "no-key"
        headers = {
            "HTTP-Referer": http_referer or "https://github.com/weebot",
            "X-Title": x_title or "weebot",
        }
        # Re-initialize the OpenAI client with custom headers
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=OPENROUTER_API_BASE,
            default_headers=headers,
        )
        self._default_model = default_model
