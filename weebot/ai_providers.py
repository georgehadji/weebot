"""
AI Provider Abstraction Layer

This module provides a clean abstraction over different AI providers
to reduce coupling between the application logic and specific provider APIs.
"""
from __future__ import annotations

import warnings
warnings.warn(
    "weebot.ai_providers is deprecated; use adapters in weebot.infrastructure.adapters.llm",
    DeprecationWarning,
    stacklevel=2,
)

import abc
import asyncio
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Protocol

from langchain_core.messages import HumanMessage
from langchain_core.language_models import BaseChatModel


class TaskType(Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    CHAT = "chat"


class ModelTier(Enum):
    PREMIUM = "premium"      # GPT-4, Kimi K2.5, Claude 3.5
    STANDARD = "standard"    # GPT-3.5, DeepSeek V3
    FAST = "fast"            # Lightweight models
    LOCAL = "local"          # Local LLMs


@dataclass
class ModelInfo:
    """Information about a specific model."""
    model_id: str
    name: str
    provider: str
    cost_per_1k_tokens: float
    context_window: int
    strengths: List[TaskType]
    tier: ModelTier
    api_key_env: str

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * self.cost_per_1k_tokens / 1000


class AIProvider(abc.ABC):
    """Abstract interface for AI providers."""

    @abc.abstractmethod
    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        """Get a chat model instance for this provider."""
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is available (API key is set)."""
        pass

    @abc.abstractmethod
    def get_models(self) -> List[ModelInfo]:
        """Get list of available models from this provider."""
        pass


class OpenAIProvider(AIProvider):
    """OpenAI API provider implementation."""

    def __init__(self):
        self._api_key = os.getenv("OPENAI_API_KEY")
        self.models = [
            ModelInfo(
                model_id="gpt-4o",
                name="GPT-4o",
                provider="openai",
                cost_per_1k_tokens=0.005,
                context_window=128000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CHAT],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENAI_API_KEY"
            ),
            ModelInfo(
                model_id="gpt-4o-mini",
                name="GPT-4o Mini",
                provider="openai",
                cost_per_1k_tokens=0.0006,
                context_window=128000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION],
                tier=ModelTier.FAST,
                api_key_env="OPENAI_API_KEY"
            ),
            ModelInfo(
                model_id="o3-mini",
                name="o3 Mini",
                provider="openai",
                cost_per_1k_tokens=0.0011,
                context_window=200000,
                strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING, TaskType.ANALYSIS, TaskType.ARCHITECTURE],
                tier=ModelTier.STANDARD,
                api_key_env="OPENAI_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_id,
            api_key=self._api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class AnthropicProvider(AIProvider):
    """Anthropic API provider implementation."""

    def __init__(self):
        self._api_key = os.getenv("ANTHROPIC_API_KEY")
        self.models = [
            ModelInfo(
                model_id="claude-3-opus-20240229",
                name="Claude 3 Opus",
                provider="anthropic",
                cost_per_1k_tokens=0.015,
                context_window=200000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.ANALYSIS, TaskType.CREATIVE],
                tier=ModelTier.PREMIUM,
                api_key_env="ANTHROPIC_API_KEY"
            ),
            ModelInfo(
                model_id="claude-3.5-sonnet",
                name="Claude 3.5 Sonnet",
                provider="anthropic",
                cost_per_1k_tokens=0.018,
                context_window=200000,
                strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.DOCUMENTATION, TaskType.CODE_GENERATION],
                tier=ModelTier.PREMIUM,
                api_key_env="ANTHROPIC_API_KEY"
            ),
            ModelInfo(
                model_id="claude-3-5-haiku-20241022",
                name="Claude 3.5 Haiku",
                provider="anthropic",
                cost_per_1k_tokens=0.0008,
                context_window=200000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
                tier=ModelTier.FAST,
                api_key_env="ANTHROPIC_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_id,
            api_key=self._api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class DeepSeekProvider(AIProvider):
    """DeepSeek API provider implementation."""

    def __init__(self):
        self._api_key = os.getenv("DEEPSEEK_API_KEY")
        self.models = [
            ModelInfo(
                model_id="deepseek-chat",
                name="DeepSeek V3",
                provider="deepseek",
                cost_per_1k_tokens=0.002,
                context_window=64000,
                strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING, TaskType.ANALYSIS],
                tier=ModelTier.STANDARD,
                api_key_env="DEEPSEEK_API_KEY"
            ),
            ModelInfo(
                model_id="deepseek-reasoner",
                name="DeepSeek R1",
                provider="deepseek",
                cost_per_1k_tokens=0.004,
                context_window=64000,
                strengths=[TaskType.ANALYSIS, TaskType.DEBUGGING, TaskType.ARCHITECTURE],
                tier=ModelTier.PREMIUM,
                api_key_env="DEEPSEEK_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_id,
            api_key=self._api_key,
            base_url="https://api.deepseek.com/v1",
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class MoonshotProvider(AIProvider):
    """Moonshot/Kimi API provider implementation."""

    def __init__(self):
        self._api_key = os.getenv("KIMI_API_KEY")
        self.models = [
            ModelInfo(
                model_id="kimi-k2.5",
                name="Kimi K2.5",
                provider="moonshot",
                cost_per_1k_tokens=0.015,
                context_window=256000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.CODE_REVIEW, TaskType.ANALYSIS],
                tier=ModelTier.PREMIUM,
                api_key_env="KIMI_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_id,
            api_key=self._api_key,
            base_url="https://api.moonshot.cn/v1",
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class GoogleProvider(AIProvider):
    """Google Gemini API provider implementation."""

    def __init__(self):
        self._api_key = os.getenv("GOOGLE_API_KEY")
        self.models = [
            ModelInfo(
                model_id="gemini-1.5-pro",
                name="Gemini 1.5 Pro",
                provider="google",
                cost_per_1k_tokens=0.0035,
                context_window=2000000,
                strengths=[TaskType.ANALYSIS, TaskType.DOCUMENTATION, TaskType.CODE_GENERATION, TaskType.ARCHITECTURE],
                tier=ModelTier.PREMIUM,
                api_key_env="GOOGLE_API_KEY"
            ),
            ModelInfo(
                model_id="gemini-2.0-flash",
                name="Gemini 2.0 Flash",
                provider="google",
                cost_per_1k_tokens=0.0001,
                context_window=1000000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
                tier=ModelTier.FAST,
                api_key_env="GOOGLE_API_KEY"
            ),
            ModelInfo(
                model_id="gemini-2.5-flash",
                name="Gemini 2.5 Flash",
                provider="google",
                cost_per_1k_tokens=0.00025,
                context_window=1000000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS, TaskType.CODE_GENERATION],
                tier=ModelTier.FAST,
                api_key_env="GOOGLE_API_KEY"
            ),
            ModelInfo(
                model_id="gemini-2.5-pro",
                name="Gemini 2.5 Pro",
                provider="google",
                cost_per_1k_tokens=0.0035,
                context_window=1000000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CREATIVE],
                tier=ModelTier.PREMIUM,
                api_key_env="GOOGLE_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_id,
            google_api_key=self._api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class XAIProvider(AIProvider):
    """xAI Grok API provider implementation (OpenAI-compatible)."""

    def __init__(self):
        self._api_key = os.getenv("XAI_API_KEY")
        self.models = [
            ModelInfo(
                model_id="grok-3",
                name="Grok 3",
                provider="xai",
                cost_per_1k_tokens=0.003,
                context_window=2000000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CHAT],
                tier=ModelTier.PREMIUM,
                api_key_env="XAI_API_KEY"
            ),
            ModelInfo(
                model_id="grok-3-mini",
                name="Grok 3 Mini",
                provider="xai",
                cost_per_1k_tokens=0.0003,
                context_window=2000000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
                tier=ModelTier.FAST,
                api_key_env="XAI_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_id,
            api_key=self._api_key,
            base_url="https://api.x.ai/v1",
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class OpenRouterProvider(AIProvider):
    """OpenRouter API provider implementation - unified access to 100+ models."""

    def __init__(self):
        self._api_key = os.getenv("OPENROUTER_API_KEY")
        self.models = [
            ModelInfo(
                model_id="openrouter/auto",
                name="OpenRouter Auto",
                provider="openrouter",
                cost_per_1k_tokens=0.005,
                context_window=2000000,
                strengths=[TaskType.CHAT, TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.CODE_REVIEW, TaskType.ARCHITECTURE, TaskType.DOCUMENTATION, TaskType.CREATIVE, TaskType.DEBUGGING],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/openai/gpt-4.1",
                name="GPT-4.1 (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.010,
                context_window=1047576,
                strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CHAT],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/openai/gpt-4.1-mini",
                name="GPT-4.1 Mini (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.002,
                context_window=1047576,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
                tier=ModelTier.STANDARD,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/openai/gpt-4o-mini",
                name="GPT-4o Mini (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.00075,
                context_window=128000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION],
                tier=ModelTier.FAST,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/anthropic/claude-3.7-sonnet",
                name="Claude 3.7 Sonnet (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.018,
                context_window=200000,
                strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.ANALYSIS],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/anthropic/claude-3.5-sonnet",
                name="Claude 3.5 Sonnet (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.018,
                context_window=200000,
                strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.CODE_GENERATION, TaskType.ARCHITECTURE],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/anthropic/claude-opus-4.6",
                name="Claude Opus 4.6 (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.030,
                context_window=1000000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.ANALYSIS, TaskType.CREATIVE],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/google/gemini-2.5-flash",
                name="Gemini 2.5 Flash (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.0005,
                context_window=1000000,
                strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
                tier=ModelTier.FAST,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/google/gemini-2.5-pro",
                name="Gemini 2.5 Pro (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.01125,
                context_window=1000000,
                strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CREATIVE],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/deepseek/deepseek-chat-v3.1",
                name="DeepSeek Chat V3.1 (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.0009,
                context_window=32768,
                strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING, TaskType.ANALYSIS],
                tier=ModelTier.STANDARD,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/deepseek/deepseek-r1-0528",
                name="DeepSeek R1 (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.0026,
                context_window=163840,
                strengths=[TaskType.ANALYSIS, TaskType.DEBUGGING, TaskType.ARCHITECTURE],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/x-ai/grok-4.1-fast",
                name="Grok 4.1 Fast (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.0007,
                context_window=2000000,
                strengths=[TaskType.CHAT, TaskType.ANALYSIS, TaskType.CODE_GENERATION],
                tier=ModelTier.STANDARD,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/meta-llama/llama-4-maverick",
                name="Llama 4 Maverick (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.00075,
                context_window=1048576,
                strengths=[TaskType.CHAT, TaskType.ANALYSIS, TaskType.CODE_GENERATION],
                tier=ModelTier.STANDARD,
                api_key_env="OPENROUTER_API_KEY"
            ),
            ModelInfo(
                model_id="openrouter/moonshotai/kimi-k2.5",
                name="Kimi K2.5 (OpenRouter)",
                provider="openrouter",
                cost_per_1k_tokens=0.0025,
                context_window=262144,
                strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.CODE_REVIEW, TaskType.ANALYSIS],
                tier=ModelTier.PREMIUM,
                api_key_env="OPENROUTER_API_KEY"
            ),
        ]

    def get_chat_model(self, model_id: str, temperature: float = 0.2, max_tokens: int = 4096) -> BaseChatModel:
        from langchain_openai import ChatOpenAI
        # OpenRouter API expects model IDs without the 'openrouter/' prefix
        api_model_id = model_id.removeprefix("openrouter/")
        return ChatOpenAI(
            model=api_model_id,
            api_key=self._api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def is_available(self) -> bool:
        return self._api_key is not None and len(self._api_key) > 0

    def get_models(self) -> List[ModelInfo]:
        return self.models


class AIProviderRegistry:
    """Registry and factory for AI providers."""

    def __init__(self):
        self._providers = {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "google": GoogleProvider(),
            "deepseek": DeepSeekProvider(),
            "moonshot": MoonshotProvider(),
            "xai": XAIProvider(),
            "openrouter": OpenRouterProvider(),
        }

    def get_provider(self, provider_name: str) -> Optional[AIProvider]:
        """Get a provider by name."""
        return self._providers.get(provider_name)

    def get_all_providers(self) -> List[AIProvider]:
        """Get all registered providers."""
        return list(self._providers.values())

    def get_available_models(self) -> List[ModelInfo]:
        """Get all available models from all providers."""
        models = []
        for provider in self._providers.values():
            if provider.is_available():
                models.extend(provider.get_models())
        return models

    def get_model_by_id(self, model_id: str) -> Optional[ModelInfo]:
        """Get a specific model by ID."""
        for provider in self._providers.values():
            if provider.is_available():
                for model in provider.get_models():
                    if model.model_id == model_id:
                        return model
        return None


# Global registry instance
_provider_registry: Optional[AIProviderRegistry] = None


def get_provider_registry() -> AIProviderRegistry:
    """Get the global provider registry instance."""
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = AIProviderRegistry()
    return _provider_registry