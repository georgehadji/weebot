"""Centralized LLM model name references.

9 allowed models — all explicit provider-qualified IDs.
``openrouter/auto`` is FORBIDDEN.

Cascade (4-tier):
  Tier 1: Owl Alpha (FREE, 1M ctx, agentic, tool use)
  Tier 2: Grok Build 0.1 (fast coding, agentic SWE)
  Tier 3: Qwen 3.7 Max (flagship coding, 1M ctx)
  Tier 4: DeepSeek V4 Pro (strongest reasoning)

Task-specific:
  CODING:        Qwen 3.7 Max + Grok Build 0.1
  FILE_OPS:      MiniMax M3 (1M ctx, multimodal, cheapest)
  RESEARCH:      Kimi K2.6 (free) — structured output
  REVIEW:        GLM-5.1 — strong instruction following
  PLANNING:      Owl Alpha (FREE, agentic, tool use)
  SECURITY:      Grok 4.3 + DeepSeek V4 Pro — reasoning, factual accuracy
  SUMMARIZATION: MiniMax M3 (fast, 1M ctx)
  GENERAL:       Owl Alpha (FREE, agentic)
"""
from __future__ import annotations

# ========================================================================
# Executor Cascade (4-tier)
# ========================================================================
MODEL_CASCADE_TIER1: str = "minimax/minimax-m3"
"""Tier 1: MiniMax M3 — FREE, 1M context, multimodal, fast, cheapest."""

MODEL_BUDGET: str = "minimax/minimax-m3"
"""Budget/free model for non-critical operations (compression, curation, defaults)."""

MODEL_CASCADE_TIER2: str = "x-ai/grok-build-0.1"
"""Tier 2: Grok Build 0.1 — fast coding model for agentic SWE workflows."""

MODEL_CASCADE_TIER3: str = "qwen/qwen3.7-max"
"""Tier 3: Qwen 3.7 Max — flagship agent-centric, coding strength, 1M context."""

MODEL_CASCADE_TIER4: str = "deepseek/deepseek-v4-pro"
"""Tier 4: DeepSeek V4 Pro — strongest reasoning, logic, math, multi-step."""

# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "minimax/minimax-m3"
"""Planning: MiniMax M3 — FREE, 1M context, multimodal, fast, cheapest."""

MODEL_CODE_REVIEW: str = "x-ai/grok-4.3"
"""Code review: Grok 4.3 — reasoning model, high factual accuracy, 1M context."""

MODEL_SUMMARIZE: str = "minimax/minimax-m3"
"""Summary: MiniMax M3 — fast, 1M context, multimodal."""

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "minimax/minimax-m3"
MODEL_DI_SKILLOPT: str = "x-ai/grok-4.3"

MODEL_FACTORY_OPENAI: str = "minimax/minimax-m3"
MODEL_FACTORY_ANTHROPIC: str = "qwen/qwen3.7-max"
MODEL_FACTORY_DEEPSEEK: str = "deepseek/deepseek-v4-pro"
MODEL_FACTORY_OPENROUTER: str = "minimax/minimax-m3"

MODEL_DEFAULT_OPENAI: str = "minimax/minimax-m3"
MODEL_DEFAULT_ANTHROPIC: str = "qwen/qwen3.7-max"
MODEL_DEFAULT_DEEPSEEK: str = "deepseek/deepseek-v4-flash"
MODEL_DEFAULT_OPENROUTER: str = "minimax/minimax-m3"

# ========================================================================
# Fallback chain
# ========================================================================
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    "minimax/minimax-m3",
    "openrouter/owl-alpha",
    "x-ai/grok-build-0.1",
    "qwen/qwen3.7-max",
    "moonshotai/kimi-k2.6:free",
    "z-ai/glm-5.1",
    "x-ai/grok-4.3",
    "deepseek/deepseek-v4-pro",
]
MODEL_FALLBACK_NON_OPENROUTER: str = "minimax/minimax-m3"

# ========================================================================
# CQRS / deprecated
# ========================================================================
MODEL_COMMAND_DEFAULT: str = "minimax/minimax-m3"
MODEL_DEPRECATED_AGENT: str = "minimax/minimax-m3"
MODEL_DEPRECATED_TOOL_AGENT: str = "minimax/minimax-m3"
MODEL_RTK_CHEAP: str = "minimax/minimax-m3"
MODEL_RTK_PREMIUM: str = "x-ai/grok-4.3"
MODEL_RTK_STANDARD: str = "qwen/qwen3.7-max"

# ========================================================================
# Mixture-of-Agents
# ========================================================================
MODEL_MOA_REFERENCE: list[str] = [
    "openrouter/owl-alpha",
    "x-ai/grok-build-0.1",
    "qwen/qwen3.7-max",
    "minimax/minimax-m3",
]

# ========================================================================
# Pricing table
# ========================================================================
MODEL_PRICE_CLAUDE_SONNET: str = "qwen/qwen3.7-max"
MODEL_PRICE_CLAUDE_OPUS: str = "x-ai/grok-4.3"
MODEL_PRICE_CLAUDE_HAIKU: str = "minimax/minimax-m3"
MODEL_PRICE_GPT4O: str = "qwen/qwen3.7-max"
MODEL_PRICE_GPT4O_MINI: str = "minimax/minimax-m3"
MODEL_PRICE_KIMI: str = "minimax/minimax-m3"
MODEL_PRICE_DEEPSEEK: str = "deepseek/deepseek-v4-flash"

# ========================================================================
# Free-tier models (canonical list)
# ========================================================================

def get_free_models() -> list[str]:
    """Return the canonical list of free-tier model IDs.

    These are referenced by model_cascade_config.py and model_selection.py.
    mooonshotai/kimi-k2.6:free is the recommended default.
    """
    return [
        "minimax/minimax-m3",
        "qwen/qwen3-coder:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3.5-content-safety:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "qwen/qwen3.6-plus:free",
        "google/gemini-2.0-flash-exp:free",
    ]
