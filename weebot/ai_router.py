#!/usr/bin/env python3
"""ai_router.py - Intelligent AI Model Selection & Cost Optimization

Λειτουργίες:
------------
1. Επιλογή βέλτιστου AI μοντέλου ανάλογα με τον τύπο εργασίας
2. Αυτόματο fallback σε εναλλακτικά μοντέλα σε περίπτωση αποτυχίας
3. Caching αποκρίσεων για μείωση κόστους
4. Παρακολούθηση κόστους και προϋπολογισμού
5. Υποστήριξη πολλαπλών providers μέσω OpenRouter και LangChain
6. Έξυπνη δρομολόγηση βασισμένη σε κόστος, επίδοση και διαθεσιμότητα

Οδηγίες Χρήσης:
---------------
1. Βασική Χρήση:
    router = ModelRouter()
    result = await router.generate_with_fallback(
        prompt="Write a Python function...",
        task_type=TaskType.CODE_GENERATION
    )

2. Με Budget Constraint:
    model_id = router.select_model(
        task_type=TaskType.CODE_GENERATION,
        budget_constraint=0.005  # max $0.005 per 1k tokens
    )

Περιβαλλοντικές Μεταβλητές:
---------------------------
- OPENAI_API_KEY: API key για OpenAI
- ANTHROPIC_API_KEY: API key για Anthropic
- GOOGLE_API_KEY: API key για Google
- AZURE_API_KEY: API key για Azure OpenAI
- AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY: API keys για AWS Bedrock
- OPENROUTER_API_KEY: API key για OpenRouter
- DEEPSEEK_API_KEY: API key για DeepSeek
- KIMI_API_KEY: API key για Moonshot Kimi
- DAILY_AI_BUDGET: Ημερήσιο όριο δαπανών (default: $10)

Ενσωματωμένοι Πάροχοι:
----------------------
- OpenAI (gpt-4o, gpt-4o-mini, gpt-3.5-turbo, κ.ά.)
- Anthropic (claude-3.5-sonnet, claude-3-opus, κ.ά.)
- Google (gemini-1.5-pro, gemini-1.5-flash, κ.ά.)
- OpenRouter (350+ μοντέλα μέσω ενιαίου API)
- DeepSeek
- Moonshot (Kimi)
- Azure OpenAI
- AWS Bedrock
- Ollama
- Hugging Face
"""
import logging
import os
import json
import hashlib
import time
import threading
import tempfile
import warnings
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from pathlib import Path
import asyncio
from datetime import date

logger = logging.getLogger(__name__)


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
    PREMIUM = "premium"      # GPT-4, Claude 3.5, etc.
    STANDARD = "standard"    # GPT-3.5, Claude Sonnet, etc.
    FAST = "fast"            # GPT-4o-mini, Claude Haiku, etc.
    LOCAL = "local"          # Local LLMs via Ollama, vLLM, etc.


@dataclass
class ModelConfig:
    name: str
    provider: str
    cost_per_1k_tokens: float
    context_window: int
    strengths: List[TaskType]
    tier: ModelTier
    api_key_env: str

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * self.cost_per_1k_tokens / 1000


class ModelRouter:
    """Intelligent routing to optimal AI models with OpenRouter support, caching and cost tracking"""

    # Define available models as class attribute for cost tracking
    MODELS = {
        # Direct providers
        "gpt-4o": ModelConfig(
            name="GPT-4o",
            provider="openai",
            cost_per_1k_tokens=0.005,
            context_window=128000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENAI_API_KEY"
        ),
        "gpt-4o-mini": ModelConfig(
            name="GPT-4o Mini",
            provider="openai",
            cost_per_1k_tokens=0.00015,
            context_window=128000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION],
            tier=ModelTier.FAST,
            api_key_env="OPENAI_API_KEY"
        ),
        "claude-3-5-sonnet-20241022": ModelConfig(
            name="Claude 3.5 Sonnet",
            provider="anthropic",
            cost_per_1k_tokens=0.003,
            context_window=200000,
            strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.DOCUMENTATION],
            tier=ModelTier.PREMIUM,
            api_key_env="ANTHROPIC_API_KEY"
        ),
        "gemini/gemini-1.5-pro": ModelConfig(
            name="Gemini 1.5 Pro",
            provider="google",
            cost_per_1k_tokens=0.0035,
            context_window=2000000,
            strengths=[TaskType.ANALYSIS, TaskType.DOCUMENTATION],
            tier=ModelTier.PREMIUM,
            api_key_env="GOOGLE_API_KEY"
        ),
        "deepseek-chat": ModelConfig(
            name="DeepSeek V3",
            provider="deepseek",
            cost_per_1k_tokens=0.002,
            context_window=64000,
            strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING, TaskType.ANALYSIS],
            tier=ModelTier.STANDARD,
            api_key_env="DEEPSEEK_API_KEY"
        ),
        "kimi-k2.5": ModelConfig(
            name="Kimi K2.5",
            provider="moonshot",
            cost_per_1k_tokens=0.015,
            context_window=256000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.CODE_REVIEW, TaskType.ANALYSIS],
            tier=ModelTier.PREMIUM,
            api_key_env="KIMI_API_KEY"
        ),
        "o3-mini": ModelConfig(
            name="o3 Mini",
            provider="openai",
            cost_per_1k_tokens=0.0011,
            context_window=200000,
            strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING, TaskType.ANALYSIS, TaskType.ARCHITECTURE],
            tier=ModelTier.STANDARD,
            api_key_env="OPENAI_API_KEY"
        ),
        "claude-3-opus-20240229": ModelConfig(
            name="Claude 3 Opus",
            provider="anthropic",
            cost_per_1k_tokens=0.015,
            context_window=200000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.ANALYSIS, TaskType.CREATIVE],
            tier=ModelTier.PREMIUM,
            api_key_env="ANTHROPIC_API_KEY"
        ),
        "claude-3-5-haiku-20241022": ModelConfig(
            name="Claude 3.5 Haiku",
            provider="anthropic",
            cost_per_1k_tokens=0.0008,
            context_window=200000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
            tier=ModelTier.FAST,
            api_key_env="ANTHROPIC_API_KEY"
        ),
        "gemini/gemini-2.0-flash": ModelConfig(
            name="Gemini 2.0 Flash",
            provider="google",
            cost_per_1k_tokens=0.0001,
            context_window=1000000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
            tier=ModelTier.FAST,
            api_key_env="GOOGLE_API_KEY"
        ),
        "gemini/gemini-2.5-flash": ModelConfig(
            name="Gemini 2.5 Flash",
            provider="google",
            cost_per_1k_tokens=0.00025,
            context_window=1000000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS, TaskType.CODE_GENERATION],
            tier=ModelTier.FAST,
            api_key_env="GOOGLE_API_KEY"
        ),
        "gemini/gemini-2.5-pro": ModelConfig(
            name="Gemini 2.5 Pro",
            provider="google",
            cost_per_1k_tokens=0.0035,
            context_window=1000000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CREATIVE],
            tier=ModelTier.PREMIUM,
            api_key_env="GOOGLE_API_KEY"
        ),
        "xai/grok-3": ModelConfig(
            name="Grok 3",
            provider="xai",
            cost_per_1k_tokens=0.003,
            context_window=2000000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CHAT],
            tier=ModelTier.PREMIUM,
            api_key_env="XAI_API_KEY"
        ),
        "xai/grok-3-mini": ModelConfig(
            name="Grok 3 Mini",
            provider="xai",
            cost_per_1k_tokens=0.0003,
            context_window=2000000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
            tier=ModelTier.FAST,
            api_key_env="XAI_API_KEY"
        ),
        # OpenRouter models
        "openrouter/auto": ModelConfig(
            name="OpenRouter Auto",
            provider="openrouter",
            cost_per_1k_tokens=0.005,
            context_window=2000000,
            strengths=[TaskType.CHAT, TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.CODE_REVIEW, TaskType.ARCHITECTURE, TaskType.DOCUMENTATION, TaskType.CREATIVE, TaskType.DEBUGGING],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/openai/gpt-4.1": ModelConfig(
            name="GPT-4.1 (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.010,
            context_window=1047576,
            strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CHAT],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/openai/gpt-4.1-mini": ModelConfig(
            name="GPT-4.1 Mini (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.002,
            context_window=1047576,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
            tier=ModelTier.STANDARD,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/openai/gpt-4o-mini": ModelConfig(
            name="GPT-4o Mini (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.00075,
            context_window=128000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION],
            tier=ModelTier.FAST,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/anthropic/claude-3.7-sonnet": ModelConfig(
            name="Claude 3.7 Sonnet (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.018,
            context_window=200000,
            strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.ANALYSIS],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/anthropic/claude-3.5-sonnet": ModelConfig(
            name="Claude 3.5 Sonnet (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.018,
            context_window=200000,
            strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.CODE_GENERATION, TaskType.ARCHITECTURE],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/anthropic/claude-opus-4.6": ModelConfig(
            name="Claude Opus 4.6 (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.030,
            context_window=1000000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.ANALYSIS, TaskType.CREATIVE],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/google/gemini-2.5-flash": ModelConfig(
            name="Gemini 2.5 Flash (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.0005,
            context_window=1000000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION, TaskType.ANALYSIS],
            tier=ModelTier.FAST,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/google/gemini-2.5-pro": ModelConfig(
            name="Gemini 2.5 Pro (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.01125,
            context_window=1000000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ANALYSIS, TaskType.ARCHITECTURE, TaskType.CREATIVE],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/deepseek/deepseek-chat-v3.1": ModelConfig(
            name="DeepSeek Chat V3.1 (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.0009,
            context_window=32768,
            strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING, TaskType.ANALYSIS],
            tier=ModelTier.STANDARD,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/deepseek/deepseek-r1-0528": ModelConfig(
            name="DeepSeek R1 (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.0026,
            context_window=163840,
            strengths=[TaskType.ANALYSIS, TaskType.DEBUGGING, TaskType.ARCHITECTURE],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/x-ai/grok-4.1-fast": ModelConfig(
            name="Grok 4.1 Fast (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.0007,
            context_window=2000000,
            strengths=[TaskType.CHAT, TaskType.ANALYSIS, TaskType.CODE_GENERATION],
            tier=ModelTier.STANDARD,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/meta-llama/llama-4-maverick": ModelConfig(
            name="Llama 4 Maverick (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.00075,
            context_window=1048576,
            strengths=[TaskType.CHAT, TaskType.ANALYSIS, TaskType.CODE_GENERATION],
            tier=ModelTier.STANDARD,
            api_key_env="OPENROUTER_API_KEY"
        ),
        "openrouter/moonshotai/kimi-k2.5": ModelConfig(
            name="Kimi K2.5 (OpenRouter)",
            provider="openrouter",
            cost_per_1k_tokens=0.0025,
            context_window=262144,
            strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE, TaskType.CODE_REVIEW, TaskType.ANALYSIS],
            tier=ModelTier.PREMIUM,
            api_key_env="OPENROUTER_API_KEY"
        ),
    }

    def __init__(self, daily_budget: float = 10.0, cache_dir: str = "./cache") -> None:
        warnings.warn(
            "ModelRouter is deprecated; use ModelSelectionService from weebot.application.services.model_selection",
            DeprecationWarning,
            stacklevel=2,
        )
        self.daily_budget = daily_budget
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cost_tracker = CostTracker(daily_budget)
        self.response_cache = ResponseCache(self.cache_dir)

    def select_model(self, task_type: TaskType,
                     budget_constraint: Optional[float] = None,
                     complexity: str = "medium") -> str:
        """Select best model for task using OpenRouter and direct providers."""
        
        # Check if any API keys are available before selecting a model
        has_any_key = any([
            os.getenv("OPENAI_API_KEY"),
            os.getenv("ANTHROPIC_API_KEY"),
            os.getenv("GOOGLE_API_KEY"),
            os.getenv("OPENROUTER_API_KEY"),
            os.getenv("DEEPSEEK_API_KEY"),
            os.getenv("KIMI_API_KEY"),
            os.getenv("XAI_API_KEY"),
        ])
        
        if not has_any_key:
            raise ValueError("No suitable model found")
        
        candidates = []
        for model_id, config in ModelRouter.MODELS.items():
            # Check if API key is available
            if not os.getenv(config.api_key_env):
                continue

            # Check budget constraint
            if budget_constraint and config.cost_per_1k_tokens > budget_constraint:
                continue

            # Calculate score
            score = 0
            if task_type in config.strengths:
                score += 10

            # Prefer cheaper models for simple tasks
            if complexity == "low":
                score -= config.cost_per_1k_tokens * 100
            elif complexity == "high":
                score += config.tier == ModelTier.PREMIUM

            candidates.append((model_id, score, config))

        if not candidates:
            # If no models match criteria, return a default based on provider availability
            if os.getenv("OPENAI_API_KEY"):
                return "gpt-4o-mini"
            elif os.getenv("OPENROUTER_API_KEY"):
                return "openrouter/openai/gpt-4o-mini"
            elif os.getenv("ANTHROPIC_API_KEY"):
                return "claude-3-5-sonnet-20241022"
            elif os.getenv("GOOGLE_API_KEY"):
                return "gemini/gemini-1.5-pro"
            else:
                raise ValueError("No API keys configured for any supported provider")

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    async def generate_with_fallback(self, prompt: str, task_type: TaskType,
                                     use_cache: bool = True, 
                                     temperature: float = 0.2,
                                     max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Generate with automatic fallback on failure using LiteLLM"""
        from weebot.domain.exceptions import BudgetExceededError

        # Check cache first — cache hits don't consume budget
        if use_cache:
            cache_key = self._generate_cache_key(prompt, task_type)
            cached = self.response_cache.get(cache_key)
            if cached:
                return {"content": cached, "source": "cache", "model": None}

        # FIX #2: Enforce daily budget BEFORE making any API call.
        # CostTracker.is_budget_exceeded() was defined but never called until now.
        if self.cost_tracker.is_budget_exceeded():
            spent = self.cost_tracker.get_stats()["today"]
            raise BudgetExceededError(
                f"Daily budget ${self.daily_budget:.2f} exceeded "
                f"(spent: ${spent:.4f}). "
                "Reset tomorrow or increase DAILY_AI_BUDGET."
            )

        # Check if this looks like a command execution request that could benefit from RTK optimization
        if self._is_command_execution_request(prompt):
            try:
                from weebot.rtk_ai_router import execute_with_token_economy
                rtk_result = await execute_with_token_economy(
                    command=prompt,
                    task_type=task_type,
                    timeout=30.0
                )
                
                if rtk_result.get("success", False):
                    content = rtk_result.get("stdout", "")
                    
                    # Track token savings if available
                    savings = rtk_result.get("token_savings_estimate", {})
                    tokens_saved = savings.get("typical_raw_tokens", 0) - savings.get("typical_optimized_tokens", 0)
                    if tokens_saved > 0:
                        self.cost_tracker.record_token_savings("rtk", tokens_saved)
                    
                    # Cache successful result
                    if use_cache:
                        cache_key = self._generate_cache_key(prompt, task_type)
                        self.response_cache.set(cache_key, content)
                    
                    return {
                        "content": content,
                        "source": "rtk_optimized",
                        "model": None,
                        "usage": {
                            "prompt_tokens": len(prompt) // 4,  # Estimated
                            "completion_tokens": len(content) // 4,  # Estimated
                            "total_tokens": (len(prompt) + len(content)) // 4,  # Estimated
                            "tokens_saved_via_rtk": tokens_saved
                        },
                        "rtk_command": rtk_result.get("rtk_command")
                    }
            except ImportError:
                logger.debug("RTK AI Router not available, skipping optimization")
                # Continue to fallback models
            except Exception as e:
                logger.warning(f"RTK optimization failed: {e}")
                # Continue to fallback models

        # Fallback to original implementation if LiteLLM is not available or fails
        try:
            model_id = self.select_model(task_type)
            result = await self._call_model(model_id, prompt, temperature, max_tokens)

            # Cache successful result
            if use_cache:
                cache_key = self._generate_cache_key(prompt, task_type)
                self.response_cache.set(cache_key, result)

            return {"content": result, "source": "api", "model": model_id}

        except Exception as e:
            # FIX #1: Use `except Exception` instead of bare `except:`.
            # Bare except swallows asyncio.CancelledError (BaseException in Python ≥3.8),
            # breaking task cancellation, timeout enforcement, and clean shutdown.
            last_error = e
            # Try fallback models
            fallback_models = self._get_fallback_models()
            for fallback_id in fallback_models:
                try:
                    result = await self._call_model(fallback_id, prompt, temperature, max_tokens)
                    return {"content": result, "source": "fallback", "model": fallback_id}
                except Exception as fallback_exc:
                    logger.warning(
                        "Fallback model %r failed: %s", fallback_id, fallback_exc
                    )
                    last_error = fallback_exc
                    continue

            raise Exception(f"All models failed. Last error: {last_error}")

    def _get_fallback_models(self) -> List[str]:
        """Get list of fallback models based on available API keys."""
        fallbacks = []
        
        if os.getenv("OPENAI_API_KEY"):
            fallbacks.extend(["gpt-4o", "o3-mini", "gpt-4o-mini", "gpt-3.5-turbo"])
        if os.getenv("ANTHROPIC_API_KEY"):
            fallbacks.extend(["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-5-haiku-20241022"])
        if os.getenv("GOOGLE_API_KEY"):
            fallbacks.extend(["gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash", "gemini/gemini-2.0-flash", "gemini/gemini-1.5-pro"])
        if os.getenv("DEEPSEEK_API_KEY"):
            fallbacks.extend(["deepseek-chat", "deepseek-reasoner"])
        if os.getenv("KIMI_API_KEY"):
            fallbacks.append("kimi-k2.5")
        if os.getenv("XAI_API_KEY"):
            fallbacks.extend(["xai/grok-3", "xai/grok-3-mini"])
        
        if os.getenv("OPENROUTER_API_KEY"):
            fallbacks.extend([
                "openrouter/auto",
                "openrouter/openai/gpt-4.1",
                "openrouter/anthropic/claude-3.7-sonnet",
                "openrouter/google/gemini-2.5-pro",
                "openrouter/google/gemini-2.5-flash",
                "openrouter/deepseek/deepseek-r1-0528",
                "openrouter/x-ai/grok-4.1-fast",
                "openrouter/meta-llama/llama-4-maverick",
                "openrouter/moonshotai/kimi-k2.5",
                "openrouter/openai/gpt-4o-mini",
                "openrouter/anthropic/claude-3.5-sonnet",
                "openrouter/deepseek/deepseek-chat-v3.1",
                "openrouter/openai/gpt-4.1-mini",
            ])
            
        return fallbacks

    def _generate_cache_key(self, prompt: str, task_type: TaskType) -> str:
        """Generate cache key for prompt"""
        content = f"{task_type.value}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def _call_model(self, model_id: str, prompt: str, 
                         temperature: float = 0.2, 
                         max_tokens: Optional[int] = None) -> str:
        """
        Call specific model API via LangChain integration.

        Supports: OpenAI, Anthropic, Google, DeepSeek, Moonshot, and OpenRouter providers.
        """

        # Determine provider from model name
        provider = "openai"  # default
        if "claude" in model_id:
            provider = "anthropic"
        elif "gemini" in model_id:
            provider = "google"
        elif "deepseek" in model_id.lower():
            provider = "deepseek"
        elif "kimi" in model_id.lower() or "moonshot" in model_id.lower():
            provider = "moonshot"
        elif "grok" in model_id.lower() or model_id.startswith("xai/"):
            provider = "xai"
        elif "openrouter" in model_id.lower():
            provider = "openrouter"
        
        # Get API key from environment
        api_key_env = self._get_api_key_env_for_provider(provider)
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ValueError(
                f"API key not found in environment: {api_key_env}. "
                f"Please set it to use {model_id}."
            )

        # Initialize appropriate client based on provider
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            client = ChatOpenAI(
                model=model_id if "gpt" in model_id else "gpt-4o-mini",
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            client = ChatAnthropic(
                model=model_id if "claude" in model_id else "claude-3-5-sonnet-20241022",
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            client = ChatGoogleGenerativeAI(
                model=model_id.replace("gemini/", ""),
                google_api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        elif provider == "deepseek":
            from langchain_openai import ChatOpenAI
            client = ChatOpenAI(
                model=model_id,
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        elif provider == "moonshot":
            from langchain_openai import ChatOpenAI
            client = ChatOpenAI(
                model=model_id,
                api_key=api_key,
                base_url="https://api.moonshot.cn/v1",
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        elif provider == "xai":
            from langchain_openai import ChatOpenAI
            api_model_id = model_id.removeprefix("xai/")
            client = ChatOpenAI(
                model=api_model_id,
                api_key=api_key,
                base_url="https://api.x.ai/v1",
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        elif provider == "openrouter":
            from langchain_openai import ChatOpenAI
            api_model_id = model_id.removeprefix("openrouter/")
            client = ChatOpenAI(
                model=api_model_id,
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=temperature,
                max_tokens=max_tokens or 4096,
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Call the model
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=prompt)]
        response = await client.ainvoke(messages)

        # Track cost if usage metadata available
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            input_tokens = response.usage_metadata.get("input_tokens", 0)
            output_tokens = response.usage_metadata.get("output_tokens", 0)
            self.cost_tracker.record_call(model_id, input_tokens, output_tokens)
        else:
            # Estimate tokens if not provided (approximate)
            estimated_input = len(prompt) // 4
            estimated_output = len(response.content) // 4
            self.cost_tracker.record_call(model_id, estimated_input, estimated_output)

        return response.content

    def _get_api_key_env_for_provider(self, provider: str) -> str:
        """Get the environment variable name for the provider's API key."""
        provider_to_env = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "moonshot": "KIMI_API_KEY",
            "xai": "XAI_API_KEY",
            "azure": "AZURE_API_KEY",
            "bedrock": "AWS_ACCESS_KEY_ID",  # AWS uses different auth mechanism
            "openrouter": "OPENROUTER_API_KEY"
        }
        return provider_to_env.get(provider, "OPENAI_API_KEY")  # Default to OpenAI

    def _is_command_execution_request(self, prompt: str) -> bool:
        """
        Determine if the prompt looks like a command execution request that could benefit from RTK optimization.
        
        Args:
            prompt: The prompt to analyze
            
        Returns:
            True if the prompt looks like a command execution request, False otherwise
        """
        # Common command patterns that benefit from RTK optimization
        command_indicators = [
            "execute", "run", "command", "bash", "shell", "terminal", 
            "ls", "git ", "grep ", "find ", "cat ", "docker ", "kubectl ",
            "npm ", "yarn ", "cargo ", "go ", "python ", "pip ", "conda ",
            "show me", "what is", "list ", "check ", "status", "analyze file",
            "read file", "find file", "search for"
        ]
        
        prompt_lower = prompt.lower()
        return any(indicator in prompt_lower for indicator in command_indicators)


class CostTracker:
    """Track daily API costs"""

    def __init__(self, daily_budget: float) -> None:
        self.daily_budget = daily_budget
        self.today_cost = 0.0
        self.call_count = 0
        self._current_day = date.today()
        self._lock = threading.Lock()

    def _ensure_today_locked(self) -> None:
        """Reset counters when the calendar day changes (lock required)."""
        today = date.today()
        if today != self._current_day:
            self._current_day = today
            self.today_cost = 0.0
            self.call_count = 0
        
    def record_call(self, model_id: str, input_tokens: int, output_tokens: int) -> None:
        """Record a model call cost."""
        with self._lock:
            self._ensure_today_locked()
            config = ModelRouter.MODELS.get(model_id)
            if config:
                cost = config.estimate_cost(input_tokens, output_tokens)
                self.today_cost += cost
                self.call_count += 1
            
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_today_locked()
            return {
                "today": self.today_cost,
                "budget": self.daily_budget,
                "remaining": self.daily_budget - self.today_cost,
                "calls": self.call_count
            }
        
    def is_budget_exceeded(self) -> bool:
        with self._lock:
            self._ensure_today_locked()
            return self.today_cost >= self.daily_budget

    def record_token_savings(self, model_id: str, tokens_saved: int) -> None:
        """Record token savings achieved through optimization (e.g., RTK)."""
        with self._lock:
            self._ensure_today_locked()
            # Token savings don't affect cost but are tracked for analytics
            # We could add a separate counter for savings if needed
            pass  # Currently just a placeholder for token savings tracking


class ResponseCache:
    """Simple file-based cache for responses"""

    def __init__(self, cache_dir: Path, ttl_hours: int = 24) -> None:
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        self._lock = threading.Lock()
        
    def get(self, key: str) -> Optional[str]:
        cache_file = self.cache_dir / f"{key}.txt"
        with self._lock:
            if cache_file.exists():
                # Check TTL
                age = time.time() - cache_file.stat().st_mtime
                if age < (self.ttl_hours * 3600):
                    return cache_file.read_text(encoding="utf-8")
        return None
        
    def set(self, key: str, value: str) -> None:
        """Store a value in cache using atomic replace."""
        cache_file = self.cache_dir / f"{key}.txt"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            tmp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.cache_dir,
                    prefix=f"{key}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp_file:
                    tmp_file.write(value)
                    tmp_path = Path(tmp_file.name)

                os.replace(tmp_path, cache_file)
            except Exception:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise
