#!/usr/bin/env python3
"""
OpenRouter Model Cascade Configuration
=======================================

Optimized model tiers for Weebot based on OpenRouter pricing and capabilities.
Fetched from: https://openrouter.ai/api/v1/models
Updated: 2026-04-05

Usage:
    from weebot.core.model_cascade_config import MODEL_CASCADE, get_model_for_task

    model = get_model_for_task("coding", tier="free")
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    id: str
    name: str
    tier: str  # free, budget, standard, premium
    prompt_price: float  # per 1M tokens
    completion_price: float  # per 1M tokens
    context_length: int
    timeout_seconds: int
    max_retries: int
    use_for: list[str]  # task types: coding, analysis, creative, chat
    description: str
    recommended: bool = False


# ============================================================================
# MODEL CASCADE CONFIGURATION
# ============================================================================

MODEL_CASCADE = {
    "coding": [
        # FREE Tier - Cost: $0
        ModelConfig(
            id="meta-llama/llama-3.3-70b-instruct:free",
            name="Llama 3.3 70B Instruct",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131072,
            timeout_seconds=30,
            max_retries=2,
            use_for=["coding", "analysis", "chat"],
            description="Best overall free model on OpenRouter. 131K context.",
            recommended=True,
        ),
        ModelConfig(
            id="qwen/qwen3-coder:free",
            name="Qwen3 Coder 480B A35B",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262000,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "refactoring", "debugging"],
            description="Best free coding model. 480B MoE specialized for code generation.",
        ),
        ModelConfig(
            id="nvidia/nemotron-3-super-120b-a12b:free",
            name="NVIDIA Nemotron 3 Super",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "analysis"],
            description="120B MoE model with 12B active parameters. Excellent for coding.",
        ),
    ],

    "analysis": [
        # FREE Tier
        ModelConfig(
            id="meta-llama/llama-3.3-70b-instruct:free",
            name="Llama 3.3 70B Instruct",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131072,
            timeout_seconds=30,
            max_retries=2,
            use_for=["coding", "analysis", "chat"],
            description="Best overall free model on OpenRouter. 131K context.",
            recommended=True,
        ),
        ModelConfig(
            id="qwen/qwen3.6-plus:free",
            name="Qwen 3.6 Plus",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1000000,
            timeout_seconds=45,
            max_retries=2,
            use_for=["analysis", "chat", "summarization"],
            description="1M context window. Great for document analysis.",
        ),
    ],

    "chat": [
        # FREE Tier
        ModelConfig(
            id="meta-llama/llama-3.3-70b-instruct:free",
            name="Llama 3.3 70B Instruct",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131072,
            timeout_seconds=30,
            max_retries=2,
            use_for=["coding", "analysis", "chat"],
            description="Best overall free model on OpenRouter.",
            recommended=True,
        ),
    ],

    "long_context": [
        # Extended context models
        ModelConfig(
            id="google/gemini-2.0-flash-exp:free",
            name="Gemini 2.0 Flash Exp",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1000000,
            timeout_seconds=60,
            max_retries=2,
            use_for=["long_context", "analysis"],
            description="1M context window (if available).",
            recommended=True,
        ),
    ],
}


# ============================================================================
# CONTEXT-AWARE MODEL SELECTION (MEMORY_ARTICLE Implementation)
# ============================================================================

# Token thresholds based on MEMORY_ARTICLE insights
TOKEN_THRESHOLDS = {
    "short_context": 4000,      # < 4K: Full precision standard attention
    "medium_context": 32000,    # 4K-32K: Standard models with good context
    "long_context": 50000,      # 32K-50K: Extended context models
    "very_long_context": 100000,  # 50K+: Sparse attention models (DeepSeek DSA)
}


def select_model_by_tokens(task_type: str, estimated_tokens: int) -> ModelConfig:
    """Select optimal model based on estimated token count."""
    # For very long contexts (50K+), use sparse attention models
    if estimated_tokens >= TOKEN_THRESHOLDS["long_context"]:
        models = MODEL_CASCADE.get("long_context", [])
        if models:
            return models[0]  # Return recommended model

    # For medium-long contexts (32K-50K), prefer extended context models
    if estimated_tokens >= TOKEN_THRESHOLDS["medium_context"]:
        models = MODEL_CASCADE.get(task_type, [])
        for model in models:
            if model.context_length >= 128000:
                return model

    # Default: use standard cascade for the task
    recommended = get_recommended_model(task_type)
    if recommended:
        return recommended

    # Ultimate fallback
    return get_recommended_model("coding")


def get_model_for_context_size(task_type: str, context_chars: int) -> ModelConfig:
    """Get appropriate model based on character count."""
    estimated_tokens = context_chars // 4
    return select_model_by_tokens(task_type, estimated_tokens)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_models_for_task(task_type: str, tier: Optional[str] = None) -> list[ModelConfig]:
    """Get models for a specific task type."""
    models = MODEL_CASCADE.get(task_type, [])
    if tier:
        models = [m for m in models if m.tier == tier]
    return models


def get_recommended_model(task_type: str, tier: Optional[str] = None) -> Optional[ModelConfig]:
    """Get the recommended model for a task."""
    models = get_models_for_task(task_type, tier)

    # First try to find a recommended model
    for model in models:
        if model.recommended:
            return model

    # Fallback to first available
    return models[0] if models else None


def get_cascade_for_task(task_type: str) -> list[ModelConfig]:
    """Get the full cascade for a task (ordered by tier)."""
    models = MODEL_CASCADE.get(task_type, [])
    tier_order = ["free", "budget", "standard", "premium"]

    # Sort by tier order
    return sorted(models, key=lambda m: tier_order.index(m.tier))


def estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost for using a model."""
    for task_models in MODEL_CASCADE.values():
        for model in task_models:
            if model.id == model_id:
                prompt_cost = (prompt_tokens / 1_000_000) * model.prompt_price
                completion_cost = (completion_tokens / 1_000_000) * model.completion_price
                return prompt_cost + completion_cost
    return 0.0


def get_model_stats() -> dict:
    """Get statistics about configured models."""
    stats = {
        "total_models": 0,
        "by_tier": {"free": 0, "budget": 0, "standard": 0, "premium": 0},
        "by_task": {},
        "recommended": 0,
    }

    for task, models in MODEL_CASCADE.items():
        stats["by_task"][task] = len(models)
        stats["total_models"] += len(models)

        for model in models:
            stats["by_tier"][model.tier] += 1
            if model.recommended:
                stats["recommended"] += 1

    return stats


# ============================================================================
# PRINT CONFIGURATION
# ============================================================================

if __name__ == "__main__":
    import sys
    print("OPENROUTER MODEL CASCADE CONFIGURATION")
    stats = get_model_stats()
    print(f"Total models: {stats['total_models']}")
