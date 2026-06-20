"""OpenAI-compatible LLM adapter implementing LLMPort."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, AuthenticationError, RateLimitError

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.config.model_refs import MODEL_DEFAULT_OPENAI
from weebot.infrastructure.adapters.llm._multimodal import convert_messages

logger = logging.getLogger(__name__)


class OpenAIAdapter(LLMPort):
    """Adapter for OpenAI-compatible APIs (OpenAI, DeepSeek, etc.)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = MODEL_DEFAULT_OPENAI,
    ):
        # API key recovery chain
        key = (
            api_key
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or "no-key"
        )

        url = base_url

        # Auto-detect base URL from model prefix or API key
        if url is None:
            model_lower = default_model.lower()
            if (
                model_lower.startswith("openrouter/")
                or "/" in default_model
                or key.startswith("sk-or-v1-")
                or os.getenv("OPENROUTER_API_KEY") == key
            ):
                url = "https://openrouter.ai/api/v1"  # kept inline — OPENROUTER_API_BASE in api_endpoints
            elif model_lower.startswith("deepseek/") or os.getenv("DEEPSEEK_API_KEY") == key:
                url = "https://api.deepseek.com"

        self._client = AsyncOpenAI(api_key=key, base_url=url)
        self._default_model = default_model

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
        response_format: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = {
            "model": model or self._default_model,
            "messages": convert_messages(messages, "openai"),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format
        
        # GPT models and reasoning models (o1, o3) often do not support 
        # the temperature parameter or use a fixed default of 1.
        # As per user instruction, GPT models do not accept temperature argument.
        model_id = kwargs["model"].lower()
        is_gpt_or_reasoning = "gpt" in model_id or any(x in model_id for x in ["o1-", "o3-", "/o1", "/o3"])
        
        if not is_gpt_or_reasoning and temperature is not None:
            kwargs["temperature"] = temperature
            
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        else:
            # Default cap to stay within OpenRouter free/credit limits.
            # Raise if your OpenRouter account has more credits, lower for tighter budget.
            kwargs["max_tokens"] = 16384

        # GLM-5.2 / Z.ai thinking mode: disable for short queries to avoid
        # truncation (thinking consumes max_tokens before visible output).
        effective_model = model or self._default_model
        if effective_model and "glm" in effective_model.lower() and max_tokens and max_tokens < 500:
            kwargs["extra_body"] = kwargs.get("extra_body", {})
            kwargs["extra_body"]["chat_template_kwargs"] = {"enable_thinking": False}

        # DeepSeek thinking mode: extra_body and reasoning_effort
        if extra_body is not None:
            kwargs["extra_body"] = {**kwargs.get("extra_body", {}), **extra_body}
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        response = None
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except AuthenticationError:
            # 401/403 — API key is invalid, expired, or lacks permissions.
            # Log clearly so the operator can rotate the key.
            key_prefix = (self._client.api_key or "")[:12]
            logger.error(
                "AUTHENTICATION ERROR: The API key (prefix: %s...) was rejected "
                "by the provider (base_url=%s). Check that the key is valid, "
                "not expired, and has the required model permissions.",
                key_prefix,
                self._client.base_url,
            )
            raise
        except RateLimitError:
            # OpenRouter free models are often rate-limited upstream.
            # Use provider-safe fallbacks first.
            model_name = str(kwargs.get("model", ""))
            is_openrouter = model_name.startswith("openrouter/") or "/" in model_name

            if is_openrouter:
                from weebot.config.model_refs import MODEL_FALLBACK_OPENROUTER_CHAIN
                fallback_models = MODEL_FALLBACK_OPENROUTER_CHAIN
            else:
                from weebot.config.model_refs import MODEL_FALLBACK_NON_OPENROUTER
                fallback_models = [MODEL_FALLBACK_NON_OPENROUTER]

            for fallback_model in fallback_models:
                if fallback_model == model_name:
                    continue
                try:
                    kwargs["model"] = fallback_model
                    response = await self._client.chat.completions.create(**kwargs)
                    break
                except RateLimitError:
                    continue
            if response is None:
                raise

        # Handle cases where response.choices is None or empty
        if not response.choices:
            error_msg = "LLM returned empty response (no choices)"
            if hasattr(response, 'error') and response.error:
                error_msg = f"LLM error: {response.error}"
            raise RuntimeError(error_msg)
        
        msg = response.choices[0].message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        usage = None
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            model=response.model or (model or self._default_model),
            usage=usage,
        )
