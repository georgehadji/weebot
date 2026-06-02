"""DeepSeek LLM adapter — OpenAI-compatible with DeepSeek base URL."""
from __future__ import annotations

import os
from typing import Optional

from .openai_adapter import OpenAIAdapter
from weebot.config.api_endpoints import DEEPSEEK_API_BASE


class DeepSeekAdapter(OpenAIAdapter):
    """Adapter for DeepSeek API (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "deepseek-chat",
    ):
        key = api_key or os.getenv("DEEPSEEK_API_KEY") or "no-key"
        super().__init__(
            api_key=key,
            base_url=DEEPSEEK_API_BASE,
            default_model=default_model,
        )
