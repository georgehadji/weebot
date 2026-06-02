"""Centralized LLM model name references.

Only 6 allowed models — all explicit provider-qualified IDs.
``openrouter/auto`` is FORBIDDEN.

Cascade (3-tier):
  Tier 1: Kimi K2.6 (free) — strong reasoning, structured output
  Tier 2: Qwen 3.7 Max — agent-centric, coding, 1M context
  Tier 3: DeepSeek V4 Pro — strongest reasoning, logic, math

Task-specific:
  CODING:        Qwen 3.7 Max — agent-centric coding flagship
  FILE_OPS:      MiniMax M3 — 1M ctx, multimodal, cheapest
  RESEARCH:      Kimi K2.6 — strong structured output
  REVIEW:        GLM-5.1 — strong instruction following
  PLANNING:      Kimi K2.6 — JSON-structured task decomposition
  SECURITY:      DeepSeek V4 Pro — best reasoning for vulnerability analysis
  SUMMARIZATION: MiniMax M3 — fast, 1M context
  GENERAL:       Kimi K2.6 — strong all-rounder
"""
from __future__ import annotations

# ========================================================================
# Executor Cascade
# ========================================================================
MODEL_CASCADE_TIER1: str = "moonshotai/kimi-k2.6:free"
"""Tier 1: Kimi K2.6 (free) — strong reasoning, task decomposition, JSON-structured output."""

MODEL_CASCADE_TIER2: str = "qwen/qwen3.7-max"
"""Tier 2: Qwen 3.7 Max — agent-centric, coding strength, 1M context, supports structured output."""

MODEL_CASCADE_TIER3: str = "deepseek/deepseek-v4-pro"
"""Tier 3: DeepSeek V4 Pro — strongest reasoning, math, logic, multi-step analysis."""

# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "moonshotai/kimi-k2.6:free"
"""Planning: Kimi K2.6 — best JSON-structured plans, task decomposition."""

MODEL_CODE_REVIEW: str = "z-ai/glm-5.1"
"""Code review: GLM-5.1 — strong instruction following, detailed critique."""

MODEL_SUMMARIZE: str = "minimax/minimax-m3"
"""Summary: MiniMax M3 — fast, 1M context, cheap."""

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "moonshotai/kimi-k2.6:free"
MODEL_DI_SKILLOPT: str = "deepseek/deepseek-v4-pro"

MODEL_FACTORY_OPENAI: str = "moonshotai/kimi-k2.6:free"
MODEL_FACTORY_ANTHROPIC: str = "qwen/qwen3.7-max"
MODEL_FACTORY_DEEPSEEK: str = "deepseek/deepseek-v4-pro"
MODEL_FACTORY_OPENROUTER: str = "moonshotai/kimi-k2.6:free"

MODEL_DEFAULT_OPENAI: str = "moonshotai/kimi-k2.6:free"
MODEL_DEFAULT_ANTHROPIC: str = "qwen/qwen3.7-max"
MODEL_DEFAULT_DEEPSEEK: str = "deepseek/deepseek-v4-flash"
MODEL_DEFAULT_OPENROUTER: str = "moonshotai/kimi-k2.6:free"

# ========================================================================
# Fallback chain
# ========================================================================
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    "moonshotai/kimi-k2.6:free",
    "qwen/qwen3.7-max",
    "minimax/minimax-m3",
    "z-ai/glm-5.1",
    "deepseek/deepseek-v4-pro",
]
MODEL_FALLBACK_NON_OPENROUTER: str = "moonshotai/kimi-k2.6:free"

# ========================================================================
# CQRS / deprecated
# ========================================================================
MODEL_COMMAND_DEFAULT: str = "moonshotai/kimi-k2.6:free"
MODEL_DEPRECATED_AGENT: str = "moonshotai/kimi-k2.6:free"
MODEL_DEPRECATED_TOOL_AGENT: str = "moonshotai/kimi-k2.6:free"
MODEL_RTK_CHEAP: str = "moonshotai/kimi-k2.6:free"
MODEL_RTK_PREMIUM: str = "deepseek/deepseek-v4-pro"
MODEL_RTK_STANDARD: str = "qwen/qwen3.7-max"

# ========================================================================
# Mixture-of-Agents
# ========================================================================
MODEL_MOA_REFERENCE: list[str] = [
    "moonshotai/kimi-k2.6:free",
    "qwen/qwen3.7-max",
    "minimax/minimax-m3",
    "z-ai/glm-5.1",
]

# ========================================================================
# Pricing table
# ========================================================================
MODEL_PRICE_CLAUDE_SONNET: str = "qwen/qwen3.7-max"
MODEL_PRICE_CLAUDE_OPUS: str = "deepseek/deepseek-v4-pro"
MODEL_PRICE_CLAUDE_HAIKU: str = "minimax/minimax-m3"
MODEL_PRICE_GPT4O: str = "qwen/qwen3.7-max"
MODEL_PRICE_GPT4O_MINI: str = "moonshotai/kimi-k2.6:free"
MODEL_PRICE_KIMI: str = "moonshotai/kimi-k2.6:free"
MODEL_PRICE_DEEPSEEK: str = "deepseek/deepseek-v4-flash"
