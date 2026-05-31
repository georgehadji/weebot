"""Factory for creating LLM adapters with resilience enabled."""
from __future__ import annotations

import os
from typing import Optional, Dict, Any

from weebot.application.ports.llm_port import LLMPort
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter

# Import concrete adapters
from weebot.infrastructure.adapters.llm.openai_adapter import OpenAIAdapter
from weebot.infrastructure.adapters.llm.anthropic_adapter import AnthropicAdapter
from weebot.infrastructure.adapters.llm.deepseek_adapter import DeepSeekAdapter
from weebot.infrastructure.adapters.llm.openrouter_adapter import OpenRouterAdapter


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
    
    # Default configurations per provider
    DEFAULT_CONFIGS: Dict[str, Dict[str, Any]] = {
        "openai": {
            "timeout": 60.0,
            "default_model": "gpt-4o-mini",
        },
        "anthropic": {
            "timeout": 90.0,  # Claude can be slower
            "default_model": "claude-3-5-sonnet-20241022",
        },
        "deepseek": {
            "timeout": 120.0,  # DeepSeek often has high latency
            "default_model": "deepseek-chat",
        },
        "openrouter": {
            "timeout": 90.0,
            "default_model": "openai/gpt-4o-mini",
        },
    }
    
    def __init__(
        self,
        default_timeout: Optional[float] = None,
        enable_circuit_breaker: Optional[bool] = None,
        enable_retry: Optional[bool] = None,
        enable_caching: Optional[bool] = None,
    ):
        """
        Initialize adapter factory.
        
        Args:
            default_timeout: Default timeout for all adapters (overrides env)
            enable_circuit_breaker: Enable circuit breaker (overrides env)
            enable_retry: Enable retry (overrides env)
            enable_caching: Enable caching (overrides env)
        """
        self._default_timeout = self._get_config(
            "LLM_TIMEOUT", default_timeout, 60.0, float
        )
        self._enable_circuit_breaker = self._get_config(
            "LLM_ENABLE_CIRCUIT_BREAKER", enable_circuit_breaker, True, bool
        )
        self._enable_retry = self._get_config(
            "LLM_ENABLE_RETRY", enable_retry, True, bool
        )
        self._enable_caching = self._get_config(
            "LLM_ENABLE_CACHING", enable_caching, False, bool
        )
        
        # Cache for created adapters
        self._adapters: Dict[str, LLMPort] = {}
    
    def _get_config(
        self,
        env_var: str,
        explicit_value: Optional[Any],
        default: Any,
        type_func: type
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
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        enable_circuit_breaker: Optional[bool] = None,
        enable_retry: Optional[bool] = None,
        enable_caching: Optional[bool] = None,
        **kwargs
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
        
        # Check cache
        cache_key = f"{provider}:{model}:{api_key}"
        if cache_key in self._adapters:
            return self._adapters[cache_key]
        
        # Get provider defaults
        defaults = self.DEFAULT_CONFIGS.get(provider, {})
        model = model or defaults.get("default_model", "unknown")
        timeout = timeout or defaults.get("timeout", self._default_timeout)
        
        # Create concrete adapter
        inner_adapter = self._create_inner_adapter(
            provider=provider,
            model=model,
            api_key=api_key,
            **kwargs
        )
        
        # Strip provider prefix for the model name used inside the adapter
        # so the inner adapter doesn't see prefixed names like "deepseek/deepseek-chat"
        stripped_model = model.split("/", 1)[-1] if "/" in model else model
        
        # Wrap with resilience
        resilient = ResilientLLMAdapter(
            inner_adapter=inner_adapter,
            model_name=f"{provider}/{stripped_model}",
            timeout=timeout,
            enable_circuit_breaker=enable_circuit_breaker if enable_circuit_breaker is not None else self._enable_circuit_breaker,
            enable_retry=enable_retry if enable_retry is not None else self._enable_retry,
            enable_caching=enable_caching if enable_caching is not None else self._enable_caching,
        )
        
        # Cache adapter
        self._adapters[cache_key] = resilient
        
        return resilient
    
    def _create_inner_adapter(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        **kwargs
    ) -> LLMPort:
        """Create the concrete adapter for the provider.

        Accepts optional ``base_url`` in kwargs for non-standard endpoints
        (moonshot, xai, google, self-hosted, etc.).
        """
        base_url = kwargs.get("base_url")

        if provider == "openai":
            # Strip provider prefix: "openai/gpt-4o-mini" → "gpt-4o-mini"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            return OpenAIAdapter(
                api_key=api_key,
                base_url=base_url,
                default_model=clean_model,
            )

        elif provider == "anthropic":
            # Strip provider prefix: "anthropic/claude-3.5-haiku" → "claude-3.5-haiku"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            return AnthropicAdapter(
                api_key=api_key,
                default_model=clean_model,
            )

        elif provider == "deepseek":
            # Strip provider prefix: "deepseek/deepseek-v4-flash" → "deepseek-v4-flash"
            clean_model = model.split("/", 1)[-1] if "/" in model else model
            return DeepSeekAdapter(
                api_key=api_key,
                default_model=clean_model,
            )

        elif provider == "openrouter":
            return OpenRouterAdapter(
                api_key=api_key,
                default_model=model,
            )

        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def get_adapter(self, provider: str, model: Optional[str] = None) -> Optional[LLMPort]:
        """Get cached adapter if it exists."""
        cache_key = f"{provider}:{model}:None"
        return self._adapters.get(cache_key)
    
    def clear_cache(self) -> None:
        """Clear the adapter cache."""
        self._adapters.clear()
    
    def list_available_providers(self) -> list[str]:
        """List available provider names."""
        return list(self.DEFAULT_CONFIGS.keys())
    
    def get_provider_config(self, provider: str) -> Dict[str, Any]:
        """Get default configuration for a provider."""
        return self.DEFAULT_CONFIGS.get(provider.lower(), {}).copy()


# Global factory instance for convenience
_default_factory: Optional[AdapterFactory] = None


def get_adapter_factory() -> AdapterFactory:
    """Get or create the default adapter factory."""
    global _default_factory
    if _default_factory is None:
        _default_factory = AdapterFactory()
    return _default_factory


def create_adapter(
    provider: str,
    model: Optional[str] = None,
    **kwargs
) -> LLMPort:
    """
    Convenience function to create an adapter using the default factory.
    
    Usage:
        adapter = create_adapter("openai", model="gpt-4o")
        response = await adapter.chat(messages=[...])
    """
    return get_adapter_factory().create_adapter(provider, model, **kwargs)
