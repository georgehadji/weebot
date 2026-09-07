"""OpenAI-compatible LLM adapter implementing LLMPort."""

from __future__ import annotations

import logging
import os
from typing import Any
from collections.abc import AsyncIterator

from openai import AsyncOpenAI, AuthenticationError, RateLimitError

from weebot.application.ports.llm_port import LLMPort, LLMResponse
from weebot.config.model_refs import MODEL_DEFAULT_OPENAI
from weebot.domain.models.llm_response import LLMChunk
from weebot.infrastructure.adapters.llm._multimodal import convert_messages

logger = logging.getLogger(__name__)


class OpenAIAdapter(LLMPort):
    """Adapter for OpenAI-compatible APIs (OpenAI, DeepSeek, etc.)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
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
        # This adapter walks a model chain of its own on RateLimitError, beneath
        # the CascadeExecutor whose job that is. Under the factory the flag is
        # turned off (see `_client_policy.apply_client_policy`); left on here so
        # an adapter constructed directly keeps the behaviour it has today.
        self._enable_model_fallback = True

    def _build_kwargs(
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
    ) -> dict[str, Any]:
        """Build the ``chat.completions.create`` kwargs.

        Shared by ``chat()`` and ``stream()`` so the considerable
        per-provider parameter munging below (thinking-mode suffixes,
        GPT/Grok/GLM quirks) exists in exactly one place and cannot
        silently drift out of sync between the two call paths.
        """
        kwargs: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": convert_messages(messages, "openai"),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format

        # Strip suffix ':thinking' if present and configure Z.AI / general thinking parameters
        if isinstance(kwargs["model"], str) and kwargs["model"].endswith(":thinking"):
            kwargs["model"] = kwargs["model"].removesuffix(":thinking")
            kwargs["extra_body"] = kwargs.get("extra_body", {}) or {}
            kwargs["extra_body"]["thinking"] = {"type": "enabled"}
            if "reasoning_effort" not in kwargs and not reasoning_effort:
                kwargs["reasoning_effort"] = "max"

        # GPT models and reasoning models (o1, o3) often do not support
        # the temperature parameter or use a fixed default of 1.
        # As per user instruction, GPT models do not accept temperature argument.
        model_id = kwargs["model"].lower()
        is_gpt_or_reasoning = "gpt" in model_id or any(
            x in model_id for x in ["o1-", "o3-", "/o1", "/o3"]
        )

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
        effective_model = kwargs["model"]
        if (
            effective_model
            and "glm" in effective_model.lower()
            and kwargs.get("max_tokens")
            and kwargs["max_tokens"] < 500
        ):
            kwargs["extra_body"] = kwargs.get("extra_body", {}) or {}
            kwargs["extra_body"]["chat_template_kwargs"] = {"enable_thinking": False}

        # x.AI Grok-specific reasoning and parameter cleanup
        if "grok" in model_id:
            # For Grok reasoning models:
            # 1. Remove presence_penalty, frequency_penalty, and stop if present to avoid API rejection errors
            kwargs.pop("presence_penalty", None)
            kwargs.pop("frequency_penalty", None)
            kwargs.pop("stop", None)

            # 2. Map reasoning_effort/thinking to x.AI format "reasoning": {"effort": ...}
            grok_effort = reasoning_effort or kwargs.get("reasoning_effort")
            if grok_effort:
                if grok_effort in ("max", "xhigh"):
                    grok_effort = "high"
                elif grok_effort in ("medium", "high"):
                    grok_effort = "high" if grok_effort == "high" else "medium"
                elif grok_effort == "minimal":
                    grok_effort = "low"

                kwargs["extra_body"] = kwargs.get("extra_body", {}) or {}
                kwargs["extra_body"]["reasoning"] = {"effort": grok_effort}
            # x.AI rejects requests where both reasoning_effort and
            # extra_body.reasoning.effort are set ("conflicting values").
            # Grok always uses the extra_body form above, so the top-level
            # key must not be reintroduced below.
            kwargs.pop("reasoning_effort", None)

        # DeepSeek thinking mode: extra_body and reasoning_effort
        if extra_body is not None:
            kwargs["extra_body"] = {**kwargs.get("extra_body", {}), **extra_body}
        if reasoning_effort is not None and "grok" not in model_id:
            kwargs["reasoning_effort"] = reasoning_effort

        return kwargs

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
        kwargs = self._build_kwargs(
            messages,
            tools,
            tool_choice,
            response_format,
            model,
            temperature,
            max_tokens,
            extra_body,
            reasoning_effort,
        )

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
            if not self._enable_model_fallback:
                raise
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
            if hasattr(response, "error") and response.error:
                error_msg = f"LLM error: {response.error}"
            raise RuntimeError(error_msg)

        msg = response.choices[0].message

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
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

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = "auto",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Stream a chat completion as ``LLMChunk`` deltas.

        Shares ``_build_kwargs`` with ``chat()`` so provider-specific
        parameter handling never drifts between the two paths. Unlike
        ``chat()``, a rate limit mid-stream is not retried — a partial
        stream has already reached the caller, so silently swapping
        models under it would produce a corrupted transcript. The
        pre-stream rate limit (bad model / no first chunk yet) still
        falls back, matching ``chat()``'s behavior.
        """
        kwargs = self._build_kwargs(
            messages, tools, tool_choice, None, model, temperature, max_tokens
        )
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        try:
            response_stream = await self._client.chat.completions.create(**kwargs)
        except AuthenticationError:
            key_prefix = (self._client.api_key or "")[:12]
            logger.error(
                "AUTHENTICATION ERROR: The API key (prefix: %s...) was rejected "
                "by the provider (base_url=%s) on stream open.",
                key_prefix,
                self._client.base_url,
            )
            raise
        except RateLimitError:
            if not self._enable_model_fallback:
                raise
            model_name = str(kwargs.get("model", ""))
            is_openrouter = model_name.startswith("openrouter/") or "/" in model_name
            if is_openrouter:
                from weebot.config.model_refs import MODEL_FALLBACK_OPENROUTER_CHAIN

                fallback_models = MODEL_FALLBACK_OPENROUTER_CHAIN
            else:
                from weebot.config.model_refs import MODEL_FALLBACK_NON_OPENROUTER

                fallback_models = [MODEL_FALLBACK_NON_OPENROUTER]

            response_stream = None
            for fallback_model in fallback_models:
                if fallback_model == model_name:
                    continue
                try:
                    kwargs["model"] = fallback_model
                    response_stream = await self._client.chat.completions.create(**kwargs)
                    break
                except RateLimitError:
                    continue
            if response_stream is None:
                raise

        effective_model = kwargs.get("model", model or self._default_model)
        async for chunk in response_stream:
            if not chunk.choices:
                # Some providers emit a usage-only trailing chunk with no choices.
                if getattr(chunk, "usage", None):
                    yield LLMChunk(
                        delta="",
                        model=getattr(chunk, "model", None) or effective_model,
                        usage={
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        },
                    )
                continue

            choice = chunk.choices[0]
            delta = choice.delta
            tool_call_deltas = None
            if getattr(delta, "tool_calls", None):
                tool_call_deltas = [
                    {
                        "index": tc.index,
                        "id": tc.id,
                        "function": {
                            "name": getattr(tc.function, "name", None),
                            "arguments": getattr(tc.function, "arguments", None),
                        },
                    }
                    for tc in delta.tool_calls
                ]

            usage = None
            if getattr(chunk, "usage", None):
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                }

            yield LLMChunk(
                delta=delta.content or "",
                tool_call_deltas=tool_call_deltas,
                finish_reason=choice.finish_reason,
                model=getattr(chunk, "model", None) or effective_model,
                usage=usage,
            )
