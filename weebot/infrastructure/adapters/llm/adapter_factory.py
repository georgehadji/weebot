"""Factory for creating LLM adapters with resilience enabled."""

from __future__ import annotations

import os
from typing import Any

from weebot.application.ports.llm_port import LLMPort
from weebot.infrastructure.adapters.llm._client_policy import apply_client_policy
from weebot.infrastructure.adapters.llm.caching_llm_adapter import (
    CachingLLMAdapter,
    supports_prompt_caching,
)
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter

# Import concrete adapters
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from weebot.infrastructure.adapters.llm.anthropic_adapter import AnthropicAdapter
from weebot.infrastructure.adapters.llm.deepseek_adapter import DeepSeekAdapter
from weebot.infrastructure.adapters.llm.moonshot_adapter import MoonshotAdapter
from weebot.infrastructure.adapters.llm.openrouter_adapter import OpenRouterAdapter
from weebot.infrastructure.adapters.llm.direct_or_fallback_adapter import DirectOrFallbackAdapter
from weebot.config.api_endpoints import XAI_API_BASE


class AdapterFactory:
    """
    Factory for creating LLM adapters with resilience patterns.

    This factory centralizes adapter creation and ensures all adapters
    are wrapped with resilience features (retry, circuit breaker, timeout).

    Usage:
        factory = AdapterFactory()
        adapter = factory.create_adapter("openai", model="gpt-4o")
        response = await adapter.chat(messages=[...])

    Configuration via environment variables:
    - LLM_TIMEOUT: Default timeout in seconds (default: 60)
    - LLM_ENABLE_CIRCUIT_BREAKER: Enable circuit breaker (default: true)
    - LLM_ENABLE_RETRY: Enable retry with backoff (default: true)
    - LLM_ENABLE_CACHING: Enable response caching (default: false)
    """

    # Default model names sourced from weebot.config.model_refs
    from weebot.config.model_refs import (
        MODEL_FACTORY_OPENAI,
        MODEL_FACTORY_ANTHROPIC,
        MODEL_FACTORY_DEEPSEEK,
        MODEL_FACTORY_OPENROUTER,
    )

    # Default configurations per provider
    DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
        "openai": {"timeout": 60.0, "default_model": MODEL_FACTORY_OPENAI},
        "anthropic": {
            "timeout": 90.0,  # Claude can be slower
            "default_model": MODEL_FACTORY_ANTHROPIC,
        },
        "deepseek": {
            "timeout": 120.0,  # DeepSeek often has high latency
            "default_model": MODEL_FACTORY_DEEPSEEK,
        },
        "moonshot": {
            "timeout": 180.0,  # Kimi K2.6 planning can take 3+ minutes
            "default_model": "kimi-k2.6",
        },
        "xai": {"timeout": 120.0, "default_model": "grok-build-0.1"},  # Grok via xAI direct API
        "openrouter": {
            "timeout": 180.0,  # Complex planning via OpenRouter can exceed 90s
            "default_model": MODEL_FACTORY_OPENROUTER,
        },
    }

    def __init__(
        self,
        default_timeout: float | None = None,
        enable_circuit_breaker: bool | None = None,
        enable_retry: bool | None = None,
        enable_caching: bool | None = None,
    ):
        """
        Initialize adapter factory.

        Args:
            default_timeout: Default timeout for all adapters (overrides env)
            enable_circuit_breaker: Enable circuit breaker (overrides env)
            enable_retry: Enable retry (overrides env)
            enable_caching: Enable caching (overrides env)
        """
        self._default_timeout = self._get_config("LLM_TIMEOUT", default_timeout, 60.0, float)
        self._enable_circuit_breaker = self._get_config(
            "LLM_ENABLE_CIRCUIT_BREAKER", enable_circuit_breaker, True, bool
        )
        self._enable_retry = self._get_config("LLM_ENABLE_RETRY", enable_retry, True, bool)
        self._enable_caching = self._get_config("LLM_ENABLE_CACHING", enable_caching, False, bool)

        # Cache for created adapters
        self._adapters: dict[str, LLMPort] = {}

    def _get_config(
        self, env_var: str, explicit_value: Any | None, default: Any, type_func: type
    ) -> Any:
        """Get configuration from explicit value, env var, or default."""
        if explicit_value is not None:
            return explicit_value

        env_value = os.getenv(env_var)
        if env_value is not None:
            if type_func == bool:
                return env_value.lower() in ("true", "1", "yes", "on")
            return type_func(env_value)

        return default

    def create_adapter(
        self,
        provider: str,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        enable_circuit_breaker: bool | None = None,
        enable_retry: bool | None = None,
        enable_caching: bool | None = None,
        **kwargs,
    ) -> LLMPort:
        """
        Create a resilient LLM adapter for the specified provider.

        Args:
            provider: Provider name (openai, anthropic, deepseek, openrouter)
            model: Model identifier (uses provider default if not specified)
            api_key: API key (uses env var if not specified)
            timeout: Request timeout in seconds
            enable_circuit_breaker: Override circuit breaker setting
            enable_retry: Override retry setting
            enable_caching: Override caching setting
            **kwargs: Additional provider-specific arguments

        Returns:
            ResilientLLMAdapter wrapping the concrete adapter
        """
        provider = provider.lower()

        # Check cache — includes caching flag so enable_caching=True/False
        # calls don't silently return the wrong adapter variant.
        _cache_flag = (
            "caching"
            if (enable_caching if enable_caching is not None else self._enable_caching)
            else "nocache"
        )
        cache_key = f"{provider}:{model}:{api_key}:{_cache_flag}"
        if cache_key in self._adapters:
            return self._adapters[cache_key]

        # Get provider defaults
        defaults = self.DEFAULT_CONFIGS.get(provider, {})
        model = model or defaults.get("default_model", "unknown")
        timeout = timeout or defaults.get("timeout", self._default_timeout)

        # Create concrete adapter
        inner_adapter = self._create_inner_adapter(
            provider=provider, model=model, api_key=api_key, **kwargs
        )

        # Push this provider's timeout budget down to the SDK client, and turn
        # off the two retry/fallback layers the wrappers above already own.
        # Without this, `timeout` bounded only the `asyncio.wait_for` below
        # while the SDK kept its own 600s read budget and its own
        # `max_retries=2`, and `OpenAIAdapter` kept a 10-model fallback chain of
        # its own — four layers whose product, measured against a 429, was 210
        # HTTP requests for one logical `chat()`. See `_client_policy`.
        apply_client_policy(
            inner_adapter, timeout=timeout, sdk_max_retries=0, model_fallback=False
        )

        # Conditionally wrap with prompt-caching adapter (Anthropic-only).
        # Injects cache_control breakpoints for Anthropic prompt caching
        # when enabled + model supports it.
        #
        # NOTE: LLM_ENABLE_CACHING / enable_caching gates TWO caches:
        #   1. Prompt caching (here) — Anthropic cache_control breakpoints
        #   2. Response caching (ResilientLLMAdapter below) — LLMCache dedup
        # These share a single knob by design. If separated in the future,
        # use distinct flags (e.g. LLM_ENABLE_PROMPT_CACHING / LLM_ENABLE_RESPONSE_CACHING).
        _do_cache = enable_caching if enable_caching is not None else self._enable_caching
        if _do_cache and supports_prompt_caching(model):
            inner_adapter = CachingLLMAdapter(
                inner_adapter=inner_adapter, model=model, enabled=True
            )

        # Strip provider prefix for the model name used inside the adapter
        # so the inner adapter doesn't see prefixed names like "deepseek/deepseek-chat"
        stripped_model = model.split("/", 1)[-1] if "/" in model else model

        # Wrap with resilience
        resilient = ResilientLLMAdapter(
            inner_adapter=inner_adapter,
            model_name=f"{provider}/{stripped_model}",
            timeout=timeout,
            enable_circuit_breaker=(
                enable_circuit_breaker
                if enable_circuit_breaker is not None
                else self._enable_circuit_breaker
            ),
            enable_retry=enable_retry if enable_retry is not None else self._enable_retry,
            enable_caching=enable_caching if enable_caching is not None else self._enable_caching,
        )

        # Cache adapter
        self._adapters[cache_key] = resilient

        return resilient

    def _create_inner_adapter(
        self, provider: str, model: str, api_key: str | None = None, **kwargs
    ) -> LLMPort:
        """Create the concrete adapter for the provider.

        Accepts optional ``base_url`` in kwargs for non-standard endpoints
        (moonshot, xai, google, self-hosted, etc.).
        """
        base_url = kwargs.get("base_url")

        if provider == "openai":
            # Strip provider prefix: "openai/gpt-4o-mini" → "gpt-4o-mini"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            return OpenAIAdapter(api_key=api_key, base_url=base_url, default_model=clean_model)

        elif provider == "anthropic":
            # Strip provider prefix: "anthropic/claude-3.5-haiku" → "claude-3.5-haiku"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            return AnthropicAdapter(api_key=api_key, default_model=clean_model)

        elif provider == "deepseek":
            # Strip provider prefix: "deepseek/deepseek-v4-flash" → "deepseek-v4-flash"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            direct = DeepSeekAdapter(api_key=api_key, default_model=clean_model)
            # If DEEPSEEK_API_KEY is set, try direct first; fall back to OpenRouter
            if _has_direct_key("DEEPSEEK_API_KEY"):
                fallback = OpenRouterAdapter(api_key=api_key, default_model=model)
                return DirectOrFallbackAdapter(
                    primary=direct,
                    secondary=fallback,
                    primary_label="deepseek-direct",
                    model_prefix="deepseek/",
                )
            # No direct key — OpenRouter only
            return OpenRouterAdapter(api_key=api_key, default_model=model)

        elif provider == "moonshot":
            # Strip OpenRouter prefix: "moonshotai/kimi-k2.6:free" → "kimi-k2.6:free"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            # Drop the ":free" suffix for direct API calls
            clean_model = clean_model.split(":")[0] if ":" in clean_model else clean_model
            direct = MoonshotAdapter(api_key=api_key, default_model=clean_model)
            # If KIMI_API_KEY or MOONSHOT_API_KEY is set, try direct first; fall back to OpenRouter.
            if _has_direct_key("KIMI_API_KEY") or _has_direct_key("MOONSHOT_API_KEY"):
                fallback = OpenRouterAdapter(api_key=api_key, default_model=model)
                return DirectOrFallbackAdapter(
                    primary=direct,
                    secondary=fallback,
                    primary_label="kimi-direct",
                    model_prefix="moonshotai/",
                )
            # No direct key — OpenRouter only
            return OpenRouterAdapter(api_key=api_key, default_model=model)

        elif provider == "minimax":
            # Strip OpenRouter prefix: "minimax/minimax-m3" → "MiniMax-M3"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            # MiniMax API supports OpenAI SDK at https://api.minimax.io
            # and Anthropic SDK at https://api.minimax.io/anthropic
            # Route through OpenRouter by default (FREE tier).
            # TODO: Add direct MiniMaxAdapter when MINIMAX_API_KEY is set.
            return OpenRouterAdapter(api_key=api_key, default_model=model)

        elif provider == "xai":
            # Strip prefix: "x-ai/grok-build-0.1" → "grok-build-0.1"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            # IMPORTANT: do NOT use the api_key parameter here — it carries
            # the OpenRouter key from create_llm_adapter.  xAI models must
            # authenticate with XAI_API_KEY against https://api.x.ai/v1.
            # Using an OpenRouter key on xAI's endpoint produces a 401.
            direct = OpenAIAdapter(
                api_key=_resolve_direct_key("XAI_API_KEY"),
                base_url=XAI_API_BASE,
                default_model=clean_model,
            )
            # If XAI_API_KEY is set, try direct first; fall back to OpenRouter
            if _has_direct_key("XAI_API_KEY"):
                fallback = OpenRouterAdapter(api_key=api_key, default_model=model)
                return DirectOrFallbackAdapter(
                    primary=direct,
                    secondary=fallback,
                    primary_label="xai-direct",
                    model_prefix="x-ai/",
                )
            # No direct key — OpenRouter only
            return OpenRouterAdapter(api_key=api_key, default_model=model)

        elif provider == "openrouter":
            return OpenRouterAdapter(api_key=api_key, default_model=model)

        else:
            raise ValueError(f"Unknown provider: {provider}")

    def get_adapter(self, provider: str, model: str | None = None) -> LLMPort | None:
        """Get a cached adapter for *provider*/*model* if one exists.

        create_adapter() keys the cache on ``provider:model:api_key:cache_flag``.
        This built ``provider:model:None`` -- three parts against four -- so the
        lookup could never hit, whatever was cached. Match on the prefix the two
        share; when several adapters differ only by api_key or caching flag, any
        of them satisfies "an adapter for this provider and model", so the first
        is returned.
        """
        prefix = f"{provider}:{model}:"
        for key, adapter in self._adapters.items():
            if key.startswith(prefix):
                return adapter
        return None

    def clear_cache(self) -> None:
        """Clear the adapter cache."""
        self._adapters.clear()

    def list_available_providers(self) -> list[str]:
        """List available provider names."""
        return list(self.DEFAULT_CONFIGS.keys())

    def get_provider_config(self, provider: str) -> dict[str, Any]:
        """Get default configuration for a provider."""
        return self.DEFAULT_CONFIGS.get(provider.lower(), {}).copy()


# Env var name → WeebotSettings field name, for provider direct-API keys.
# Single source of truth for both _resolve_direct_key() and _has_direct_key().
_SETTINGS_FIELD_MAP: dict[str, str] = {
    "XAI_API_KEY": "xai_api_key",
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "KIMI_API_KEY": "kimi_api_key",
    "MOONSHOT_API_KEY": "kimi_api_key",  # both map to kimi
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
}


def _resolve_direct_key(env_var: str) -> str | None:
    """Resolve a provider's direct API key: .env-backed settings first
    (overrides stale system env vars), falling back to raw os.getenv.

    This is the one canonical resolution path for provider direct-API keys —
    used both to fetch the key value (here) and to check its presence
    (``_has_direct_key``), so the two can never disagree.
    """
    field = _SETTINGS_FIELD_MAP.get(env_var)
    if field:
        try:
            from weebot.config.settings import WeebotSettings

            val = getattr(WeebotSettings(), field, None)
            if val and val.strip():
                return val
        except Exception:
            pass
    return os.getenv(env_var) or None


def _has_direct_key(env_var: str) -> bool:
    """Return True if the given API key env var is set to a non-empty value."""
    return bool(_resolve_direct_key(env_var))


# Global factory instance for convenience
_default_factory: AdapterFactory | None = None


def get_adapter_factory() -> AdapterFactory:
    """Get or create the default adapter factory."""
    global _default_factory
    if _default_factory is None:
        _default_factory = AdapterFactory()
    return _default_factory


def create_adapter(provider: str, model: str | None = None, **kwargs) -> LLMPort:
    """
    Convenience function to create an adapter using the default factory.

    Usage:
        adapter = create_adapter("openai", model="gpt-4o")
        response = await adapter.chat(messages=[...])
    """
    return get_adapter_factory().create_adapter(provider, model, **kwargs)
