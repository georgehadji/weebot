#!/usr/bin/env python3
"""
OpenRouter Model Cascade Configuration
=======================================

Optimized model tiers for Weebot based on OpenRouter pricing and capabilities.
Fetched from: https://openrouter.ai/api/v1/models
Updated: 2026-06-09

**This is the configuration source only.** The canonical cascade execution
logic lives in ``ExecutorAgent._call_with_cascade()`` at
``weebot/application/agents/executor.py``.  That method handles parallel
Phase 1 dispatch, sequential Phase 2 fallback, per-model circuit breakers,
and 2s timeouts — all driven by the tier constants defined here.

The former ``ModelCascadeService`` in ``model_cascade_integration.py`` was
removed (2026-04) — it contained a hardcoded placeholder that never called
a real LLM.  If you need cascade execution, use ``ExecutorAgent`` or
instantiate an ``OpenRouterAdapter`` directly via the DI container.

Usage:
    from weebot.core.model_cascade_config import MODEL_CASCADE, get_model_for_task

    model = get_model_for_task("coding", tier="free")

Pricing notes (2026-06-09, per 1M tokens):
  - Models without the :free suffix route to paid endpoints even if they have
    a free variant. Always use model_id:free to hit the free tier.
  - deepseek/deepseek-v4-flash has NO free variant; use it as a budget model.
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
        # --- FREE tier ---
        ModelConfig(
            id="qwen/qwen3-coder:free",
            name="Qwen3 Coder 480B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1049000,
            timeout_seconds=60,
            max_retries=2,
            use_for=["coding", "refactoring", "debugging", "analysis"],
            description="Qwen3-Coder-480B MoE — purpose-built coding specialist, 1M context.",
        ),
        ModelConfig(
            id="poolside/laguna-m.1:free",
            name="Poolside Laguna M.1 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=60,
            max_retries=2,
            use_for=["coding", "refactoring", "debugging"],
            description="Poolside flagship coding-agent model — optimised for complex SWE tasks.",
        ),
        ModelConfig(
            id="moonshotai/kimi-k2.6:free",
            name="Kimi K2.6 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "analysis", "chat", "planning"],
            description="Kimi K2.6 free tier — long-horizon coding, planning, 256K context.",
        ),
        ModelConfig(
            id="poolside/laguna-xs.2:free",
            name="Poolside Laguna XS.2 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=30,
            max_retries=2,
            use_for=["coding", "subagent"],
            description="Poolside efficient coding model — fast, for subagent/inline tasks.",
        ),
        # --- BUDGET tier ---
        ModelConfig(
            id="deepseek/deepseek-v4-flash:thinking",
            name="DeepSeek V4 Flash :thinking",
            tier="budget",
            prompt_price=0.0983,
            completion_price=0.1966,
            context_length=1049000,
            timeout_seconds=30,
            max_retries=2,
            use_for=["coding", "refactoring", "debugging", "analysis"],
            description="DeepSeek V4 Flash :thinking — $0.10/1M, 1M context, CoT reasoning for coding.",
            recommended=True,
        ),
        ModelConfig(
            id="qwen/qwen3-coder-30b-a3b-instruct",
            name="Qwen3 Coder 30B",
            tier="budget",
            prompt_price=0.07,
            completion_price=0.27,
            context_length=160000,
            timeout_seconds=30,
            max_retries=2,
            use_for=["coding", "refactoring"],
            description="Qwen3 Coder 30B — cheapest dedicated coding model at $0.07/1M.",
        ),
        ModelConfig(
            id="x-ai/grok-build-0.1",
            name="Grok Build 0.1",
            tier="budget",
            prompt_price=1.0,
            completion_price=2.0,
            context_length=256000,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "analysis"],
            description="Grok Build 0.1 — xAI agentic SWE model, $1/1M.",
        ),
    ],

    "analysis": [
        # --- FREE tier ---
        ModelConfig(
            id="moonshotai/kimi-k2.6:free",
            name="Kimi K2.6 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "analysis", "chat", "planning"],
            description="Kimi K2.6 free tier — long-horizon analysis fallback.",
        ),
        ModelConfig(
            id="nex-agi/nex-n2-pro:free",
            name="Nex N2 Pro (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=30,
            max_retries=2,
            use_for=["analysis", "chat", "planning"],
            description="Nex N2 Pro — 397B MoE, agentic-tuned, cross-lab diversity.",
        ),
        ModelConfig(
            id="nvidia/nemotron-3-ultra-550b-a55b:free",
            name="Nemotron 3 Ultra 550B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1000000,
            timeout_seconds=90,
            max_retries=2,
            use_for=["analysis", "planning", "long_context"],
            description="NVIDIA 550B frontier reasoning/orchestration model, 1M context.",
        ),
        # --- BUDGET tier ---
        ModelConfig(
            id="deepseek/deepseek-v4-flash:thinking",
            name="DeepSeek V4 Flash :thinking",
            tier="budget",
            prompt_price=0.0983,
            completion_price=0.1966,
            context_length=1049000,
            timeout_seconds=30,
            max_retries=2,
            use_for=["analysis", "chat", "summarization"],
            description="DeepSeek V4 Flash :thinking — $0.10/1M, 1M context, CoT reasoning for analysis.",
            recommended=True,
        ),
    ],

    "chat": [
        # --- FREE tier ---
        ModelConfig(
            id="moonshotai/kimi-k2.6:free",
            name="Kimi K2.6 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "analysis", "chat"],
            description="Kimi K2.6 free tier — chat fallback.",
        ),
        ModelConfig(
            id="nex-agi/nex-n2-pro:free",
            name="Nex N2 Pro (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=30,
            max_retries=2,
            use_for=["chat"],
            description="Nex N2 Pro — cross-lab diversity for chat.",
        ),
        ModelConfig(
            id="meta-llama/llama-3.3-70b-instruct:free",
            name="Llama 3.3 70B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131000,
            timeout_seconds=30,
            max_retries=2,
            use_for=["chat", "summarization"],
            description="Meta Llama 3.3 70B — battle-tested, reliable, multilingual.",
        ),
        # --- BUDGET tier ---
        ModelConfig(
            id="deepseek/deepseek-v4-flash",
            name="DeepSeek V4 Flash",
            tier="budget",
            prompt_price=0.0983,
            completion_price=0.1966,
            context_length=1049000,
            timeout_seconds=30,
            max_retries=2,
            use_for=["chat", "analysis"],
            description="DeepSeek V4 Flash — $0.10/1M, 1M context, recommended for chat.",
            recommended=True,
        ),
    ],

    "planning": [
        # --- FREE tier ---
        ModelConfig(
            id="moonshotai/kimi-k2.6:free",
            name="Kimi K2.6 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=45,
            max_retries=2,
            use_for=["coding", "analysis", "planning"],
            description="Kimi K2.6 free tier — planning fallback.",
        ),
        ModelConfig(
            id="nvidia/nemotron-3-ultra-550b-a55b:free",
            name="Nemotron 3 Ultra 550B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1000000,
            timeout_seconds=90,
            max_retries=2,
            use_for=["planning", "analysis", "long_context"],
            description="NVIDIA 550B frontier orchestration model — deep reasoning for plans.",
        ),
        ModelConfig(
            id="nousresearch/hermes-3-llama-3.1-405b:free",
            name="Hermes 3 405B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131000,
            timeout_seconds=60,
            max_retries=2,
            use_for=["planning", "analysis"],
            description="Hermes 3 405B — advanced agentic capabilities, tool use, planning.",
        ),
        # --- STANDARD tier ---
        ModelConfig(
            id="z-ai/glm-5.2:thinking",
            name="GLM 5.2 :thinking",
            tier="standard",
            prompt_price=0.95,
            completion_price=3.0,
            context_length=1049000,
            timeout_seconds=60,
            max_retries=2,
            use_for=["planning", "analysis", "coding"],
            description="Z.ai GLM 5.2 :thinking — reasoning model (effort=xhigh), 1M context, Design Arena #1 coding.",
            recommended=True,
        ),
        # --- BUDGET tier ---
        ModelConfig(
            id="deepseek/deepseek-v4-flash",
            name="DeepSeek V4 Flash",
            tier="budget",
            prompt_price=0.0983,
            completion_price=0.1966,
            context_length=1049000,
            timeout_seconds=45,
            max_retries=2,
            use_for=["planning", "analysis"],
            description="DeepSeek V4 Flash — fast, 1M context, budget planning fallback.",
        ),
    ],

    "subagent": [
        # Lightweight models for frequent, short-lived subagent calls
        ModelConfig(
            id="openai/gpt-oss-20b:free",
            name="GPT OSS 20B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131000,
            timeout_seconds=20,
            max_retries=3,
            use_for=["subagent", "chat", "analysis"],
            description="OpenAI 21B MoE — fast, Apache 2.0, subagent dispatch fallback.",
        ),
        ModelConfig(
            id="poolside/laguna-xs.2:free",
            name="Poolside Laguna XS.2 (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=262144,
            timeout_seconds=20,
            max_retries=3,
            use_for=["subagent", "coding"],
            description="Poolside efficient coding subagent — fast, 262K context.",
        ),
        ModelConfig(
            id="meta-llama/llama-3.3-70b-instruct:free",
            name="Llama 3.3 70B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=131000,
            timeout_seconds=25,
            max_retries=3,
            use_for=["subagent", "chat"],
            description="Meta Llama 3.3 70B — reliable, versatile subagent fallback.",
        ),
        # --- BUDGET tier ---
        ModelConfig(
            id="openai/gpt-4.1-nano",
            name="GPT-4.1 Nano",
            tier="budget",
            prompt_price=0.1,
            completion_price=0.4,
            context_length=1048000,
            timeout_seconds=20,
            max_retries=3,
            use_for=["subagent", "chat"],
            description="OpenAI GPT-4.1 Nano — $0.10/1M, 1M context, recommended for subagent.",
            recommended=True,
        ),
    ],

    "long_context": [
        # Models with >= 500K context for very large inputs
        ModelConfig(
            id="nvidia/nemotron-3-ultra-550b-a55b:free",
            name="Nemotron 3 Ultra 550B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1000000,
            timeout_seconds=120,
            max_retries=2,
            use_for=["long_context", "analysis", "planning"],
            description="NVIDIA 550B frontier model — 1M context, giant-input fallback.",
        ),
        ModelConfig(
            id="qwen/qwen3-coder:free",
            name="Qwen3 Coder 480B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1049000,
            timeout_seconds=90,
            max_retries=2,
            use_for=["long_context", "coding"],
            description="Qwen3 Coder 480B — 1M context, ideal for large codebases.",
        ),
        ModelConfig(
            id="nvidia/nemotron-3-super-120b-a12b:free",
            name="Nemotron 3 Super 120B (free)",
            tier="free",
            prompt_price=0.0,
            completion_price=0.0,
            context_length=1000000,
            timeout_seconds=90,
            max_retries=2,
            use_for=["long_context", "analysis"],
            description="NVIDIA 120B hybrid MoE — 1M context, efficient long-context fallback.",
        ),
        # --- BUDGET tier ---
        ModelConfig(
            id="meta-llama/llama-4-scout",
            name="Llama 4 Scout",
            tier="budget",
            prompt_price=0.1,
            completion_price=0.3,
            context_length=10000000,
            timeout_seconds=120,
            max_retries=2,
            use_for=["long_context", "analysis"],
            description="Meta Llama 4 Scout — $0.10/1M, 10M context, recommended for long context.",
            recommended=True,
        ),
    ],
}


# ============================================================================
# CONTEXT-AWARE MODEL SELECTION (MEMORY_ARTICLE Implementation)
# ============================================================================

# Token thresholds based on MEMORY_ARTICLE insights
TOKEN_THRESHOLDS = {
    "short_context": 4000,        # < 4K: Full precision standard attention
    "medium_context": 32000,      # 4K-32K: Standard models with good context
    "long_context": 50000,        # 32K-50K: Extended context models
    "very_long_context": 100000,  # 50K+: Sparse attention / giant-context models
}


def select_model_by_tokens(task_type: str, estimated_tokens: int) -> ModelConfig:
    """Select optimal model based on estimated token count."""
    if estimated_tokens >= TOKEN_THRESHOLDS["long_context"]:
        recommended = get_recommended_model("long_context")
        if recommended:
            return recommended

    if estimated_tokens >= TOKEN_THRESHOLDS["medium_context"]:
        # Prefer recommended (paid) model; fall back to first model with sufficient context
        models = MODEL_CASCADE.get(task_type, [])
        recommended = get_recommended_model(task_type)
        if recommended:
            return recommended
        for model in models:
            if model.context_length >= 128000:
                return model

    recommended = get_recommended_model(task_type)
    if recommended:
        return recommended

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
    for model in models:
        if model.recommended:
            return model
    return models[0] if models else None


def get_cascade_for_task(task_type: str) -> list[ModelConfig]:
    """Get the full cascade for a task (ordered by tier)."""
    models = MODEL_CASCADE.get(task_type, [])
    tier_order = ["free", "budget", "standard", "premium"]
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
# Phase 4: Cross-Lab Role Model Config
# ============================================================================
# Maps functional agent roles to ordered model lists.
# Design rule: "planner" and "critic" must use models from *different* labs
# to prevent echo-chamber plan validation.
#
# Lab diversity map:
#   Qwen (Alibaba) · Moonshot · NVIDIA · OpenAI · Meta · Poolside · DeepSeek
#   NousResearch · Nex AGI · xAI · Google
#
# Each entry: [primary, fallback1, fallback2, ...]
# Falls back to the flow's default model if the role is not configured.

AGENT_ROLES = frozenset({
    "planner",    # generates initial plans
    "critic",     # validates plans (PlanCriticService, MetaCritic)
    "executor",   # executes steps (ExecutorAgent)
    "verifier",   # CoVe verification (VerifyingState)
    "summarizer", # SummarizingState
    "subagent",   # lightweight parallel sub-tasks
})

