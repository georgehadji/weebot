#!/usr/bin/env python3
"""ai_router.py - Intelligent AI Model Selection & Cost Optimization

Λειτουργίες:
------------
1. Επιλογή βέλτιστου AI μοντέλου ανάλογα με τον τύπο εργασίας
2. Αυτόματο fallback σε εναλλακτικά μοντέλα σε περίπτωση αποτυχίας
3. Caching αποκρίσεων για μείωση κόστους
4. Παρακολούθηση κόστους και προϋπολογισμού
5. Υποστήριξη πολλαπλών providers (Kimi, DeepSeek, Anthropic, OpenAI)

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
- KIMI_API_KEY: API key για Moonshot AI
- DEEPSEEK_API_KEY: API key για DeepSeek
- ANTHROPIC_API_KEY: API key για Anthropic
- OPENAI_API_KEY: API key για OpenAI
- DAILY_AI_BUDGET: Ημερήσιο όριο δαπανών (default: $10)
"""
import logging
import os
import json
import hashlib
import time
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from pathlib import Path
import asyncio

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
    PREMIUM = "premium"      # GPT-4, Kimi K2.5, Claude 3.5
    STANDARD = "standard"    # GPT-3.5, DeepSeek V3
    FAST = "fast"            # Lightweight models
    LOCAL = "local"          # Local LLMs


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
    """Intelligent routing to optimal AI models with caching and cost tracking"""
    
    MODELS = {
        "kimi-k2.5": ModelConfig(
            name="Kimi K2.5",
            provider="moonshot",
            cost_per_1k_tokens=0.015,
            context_window=256000,
            strengths=[TaskType.CODE_GENERATION, TaskType.ARCHITECTURE,
                       TaskType.CODE_REVIEW, TaskType.ANALYSIS],
            tier=ModelTier.PREMIUM,
            api_key_env="KIMI_API_KEY"
        ),
        "deepseek-chat": ModelConfig(
            name="DeepSeek V3",
            provider="deepseek",
            cost_per_1k_tokens=0.002,
            context_window=64000,
            strengths=[TaskType.CODE_GENERATION, TaskType.DEBUGGING,
                       TaskType.ANALYSIS],
            tier=ModelTier.STANDARD,
            api_key_env="DEEPSEEK_API_KEY"
        ),
        "deepseek-reasoner": ModelConfig(
            name="DeepSeek R1",
            provider="deepseek",
            cost_per_1k_tokens=0.004,
            context_window=64000,
            strengths=[TaskType.ANALYSIS, TaskType.DEBUGGING, TaskType.ARCHITECTURE],
            tier=ModelTier.PREMIUM,
            api_key_env="DEEPSEEK_API_KEY"
        ),
        "claude-3.5-sonnet": ModelConfig(
            name="Claude 3.5 Sonnet",
            provider="anthropic",
            cost_per_1k_tokens=0.018,
            context_window=200000,
            strengths=[TaskType.CODE_REVIEW, TaskType.CREATIVE, TaskType.DOCUMENTATION],
            tier=ModelTier.PREMIUM,
            api_key_env="ANTHROPIC_API_KEY"
        ),
        "gpt-4o-mini": ModelConfig(
            name="GPT-4o Mini",
            provider="openai",
            cost_per_1k_tokens=0.0006,
            context_window=128000,
            strengths=[TaskType.CHAT, TaskType.DOCUMENTATION],
            tier=ModelTier.FAST,
            api_key_env="OPENAI_API_KEY"
        ),
    }
    
    def __init__(self, daily_budget: float = 10.0, cache_dir: str = "./cache") -> None:
        self.daily_budget = daily_budget
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cost_tracker = CostTracker(daily_budget)
        self.response_cache = ResponseCache(self.cache_dir)
        
    def select_model(self, task_type: TaskType, 
                     budget_constraint: Optional[float] = None,
                     complexity: str = "medium") -> str:
        """Select best model for task based on capabilities and cost"""
        
        candidates = []
        for model_id, config in self.MODELS.items():
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
            raise ValueError("No suitable model found for task")
            
        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]
    
    async def generate_with_fallback(self, prompt: str, task_type: TaskType,
                                     use_cache: bool = True) -> Dict[str, Any]:
        """Generate with automatic fallback on failure"""
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
            raise BudgetExceededError(
                f"Daily budget ${self.daily_budget:.2f} exceeded "
                f"(spent: ${self.cost_tracker.today_cost:.4f}). "
                "Reset tomorrow or increase DAILY_AI_BUDGET."
            )

        # Try primary model
        model_id = self.select_model(task_type)
        try:
            result = await self._call_model(model_id, prompt)

            # Cache successful result
            if use_cache:
                self.response_cache.set(cache_key, result)

            return {"content": result, "source": "api", "model": model_id}

        except Exception as e:
            # FIX #1: Use `except Exception` instead of bare `except:`.
            # Bare except swallows asyncio.CancelledError (BaseException in Python ≥3.8),
            # breaking task cancellation, timeout enforcement, and clean shutdown.
            last_error = e
            for fallback_id in [m for m in self.MODELS.keys() if m != model_id]:
                try:
                    result = await self._call_model(fallback_id, prompt)
                    return {"content": result, "source": "fallback", "model": fallback_id}
                except Exception as fallback_exc:
                    logger.warning(
                        "Fallback model %r failed: %s", fallback_id, fallback_exc
                    )
                    last_error = fallback_exc
                    continue

            raise Exception(f"All models failed. Last error: {last_error}")
    
    def _generate_cache_key(self, prompt: str, task_type: TaskType) -> str:
        """Generate cache key for prompt"""
        content = f"{task_type.value}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def _call_model(self, model_id: str, prompt: str) -> str:
        """
        Call specific model API via LangChain integration.
        
        Supports: OpenAI, Anthropic, DeepSeek
        """
        config = self.MODELS[model_id]
        
        # Get API key from environment
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise ValueError(
                f"API key not found in environment: {config.api_key_env}. "
                f"Please set it to use {config.name}."
            )
        
        # Initialize appropriate client based on provider
        if config.provider == "openai":
            from langchain_openai import ChatOpenAI
            client = ChatOpenAI(
                model=model_id if "gpt" in model_id else "gpt-4o-mini",
                api_key=api_key,
                temperature=0.2,
                max_tokens=4096,
            )
        elif config.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            client = ChatAnthropic(
                model=model_id if "claude" in model_id else "claude-3-5-sonnet-20241022",
                api_key=api_key,
                temperature=0.2,
                max_tokens=4096,
            )
        elif config.provider == "deepseek":
            from langchain_openai import ChatOpenAI
            # DeepSeek uses OpenAI-compatible API
            client = ChatOpenAI(
                model=model_id,
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=0.2,
                max_tokens=4096,
            )
        elif config.provider == "moonshot":
            from langchain_openai import ChatOpenAI
            # Kimi uses OpenAI-compatible API
            client = ChatOpenAI(
                model=model_id,
                api_key=api_key,
                base_url="https://api.moonshot.cn/v1",
                temperature=0.2,
                max_tokens=4096,
            )
        else:
            raise ValueError(f"Unknown provider: {config.provider}")
        
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


class CostTracker:
    """Track daily API costs"""

    def __init__(self, daily_budget: float) -> None:
        self.daily_budget = daily_budget
        self.today_cost = 0.0
        self.call_count = 0
        
    def record_call(self, model_id: str, input_tokens: int, output_tokens: int) -> None:
        """Record a model call cost."""
        config = ModelRouter.MODELS.get(model_id)
        if config:
            cost = config.estimate_cost(input_tokens, output_tokens)
            self.today_cost += cost
            self.call_count += 1
            
    def get_stats(self) -> Dict[str, Any]:
        return {
            "today": self.today_cost,
            "budget": self.daily_budget,
            "remaining": self.daily_budget - self.today_cost,
            "calls": self.call_count
        }
        
    def is_budget_exceeded(self) -> bool:
        return self.today_cost >= self.daily_budget


class ResponseCache:
    """Simple file-based cache for responses"""

    def __init__(self, cache_dir: Path, ttl_hours: int = 24) -> None:
        self.cache_dir = cache_dir
        self.ttl_hours = ttl_hours
        
    def get(self, key: str) -> Optional[str]:
        cache_file = self.cache_dir / f"{key}.txt"
        if cache_file.exists():
            # Check TTL
            age = time.time() - cache_file.stat().st_mtime
            if age < (self.ttl_hours * 3600):
                return cache_file.read_text()
        return None
        
    def set(self, key: str, value: str) -> None:
        """Store a value in cache."""
        cache_file = self.cache_dir / f"{key}.txt"
        cache_file.write_text(value)
