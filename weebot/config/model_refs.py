"""Centralized LLM model name references.

Single source of truth for model strings used outside the
:mod:`weebot.application.services.model_selection` registry.
Change a model name here and it propagates everywhere.

Naming convention: ``MODEL_<PROVIDER>_<PURPOSE>``.
"""
from __future__ import annotations

# ========================================================================
# Budget / primary model
# ========================================================================
MODEL_BUDGET: str = "moonshotai/kimi-k2.6"
"""Default budget-tier model for interactive mode and executor cascade."""

MODEL_CASCADE_FREE: str = "minimax/minimax-m3"
"""First-attempt model in executor cascade (1M context, $0.0008/1K)."""

MODEL_CODE_REVIEW: str = "anthropic/claude-sonnet-4.6"
"""Model used for code review tasks (Claude excels at critique/analysis)."""


# ========================================================================
# Adapter constructor defaults
# ========================================================================
MODEL_DEFAULT_OPENAI: str = "gpt-4o-mini"
"""Default model in OpenAIAdapter when no model is passed."""

MODEL_DEFAULT_ANTHROPIC: str = "claude-3-5-sonnet-20241022"
"""Default model in AnthropicAdapter when no model is passed."""

MODEL_DEFAULT_DEEPSEEK: str = "deepseek-chat"
"""Default model in DeepSeekAdapter when no model is passed."""

MODEL_DEFAULT_OPENROUTER: str = "openrouter/auto"
"""Default model in OpenRouterAdapter when no model is passed."""


# ========================================================================
# AdapterFactory provider-level defaults
# ========================================================================
MODEL_FACTORY_OPENAI: str = "gpt-4o-mini"
"""Factory default model for the 'openai' provider."""

MODEL_FACTORY_ANTHROPIC: str = "claude-3-5-sonnet-20241022"
"""Factory default model for the 'anthropic' provider."""

MODEL_FACTORY_DEEPSEEK: str = "deepseek-chat"
"""Factory default model for the 'deepseek' provider."""

MODEL_FACTORY_OPENROUTER: str = "openai/gpt-4o-mini"
"""Factory default model for the 'openrouter' provider."""


# ========================================================================
# Rate-limit and error fallback chains
# ========================================================================
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    "openrouter/auto",
    "openrouter/openai/gpt-4o-mini",
    "deepseek/deepseek-chat",
]
"""Fallback models tried in order on OpenRouter rate-limit (429)."""

MODEL_FALLBACK_NON_OPENROUTER: str = "gpt-4o-mini"
"""Fallback when non-OpenRouter rate-limit is hit."""


# ========================================================================
# Cascade model config (free/budget tiers)
# ========================================================================
MODEL_CASCADE_FREE_LLAMA: str = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_CASCADE_FREE_QWEN: str = "qwen/qwen3-coder:free"
MODEL_CASCADE_FREE_NVIDIA: str = "nvidia/nemotron-3-super-120b-a12b:free"
MODEL_CASCADE_FREE_QWEN_PLUS: str = "qwen/qwen3.6-plus:free"
MODEL_CASCADE_FREE_GEMINI: str = "google/gemini-2.0-flash-exp:free"

MODEL_MINIMAX_M3: str = "minimax/minimax-m3"
"""MiniMax M3 — 1M context, strong agentic/reasoning/coding capabilities."""


# ========================================================================
# DI container defaults
# ========================================================================
MODEL_DI_FALLBACK: str = "openrouter/auto"
"""DI container fallback when no model is configured."""

MODEL_DI_SKILLOPT: str = "anthropic/claude-sonnet-4.6"
"""SkillOpt optimizer model in DI container."""


# ========================================================================
# CQRS command defaults
# ========================================================================
MODEL_COMMAND_DEFAULT: str = "gpt-4"
"""Default model in CreatePlanCommand and deprecated agents."""


# ========================================================================
# Deprecated agent fallbacks
# ========================================================================
MODEL_DEPRECATED_AGENT: str = "gpt-4"
"""Hard-coded model in deprecated OEAR agent (core/agent.py)."""

MODEL_DEPRECATED_TOOL_AGENT: str = "gpt-4o-mini"
"""Hard-coded model in deprecated ToolCallAgent (core/tool_agent.py)."""


# ========================================================================
# ai_router.py fallback result strings
# ========================================================================
MODEL_ROUTER_OPENAI_FALLBACK: str = "gpt-4o-mini"
MODEL_ROUTER_OPENROUTER_FALLBACK: str = "openrouter/openai/gpt-4o-mini"
MODEL_ROUTER_ANTHROPIC_FALLBACK: str = "claude-3-5-sonnet-20241022"
MODEL_ROUTER_GOOGLE_FALLBACK: str = "gemini/gemini-1.5-pro"
"""Provider fallback return values in ai_router.py selection logic."""

MODEL_RTK_CHEAP: str = "gpt-4o-mini"
"""Budget model for RTK-routed tasks when cost is constrained."""
MODEL_RTK_PREMIUM: str = "gpt-4o"
"""Premium model for RTK-routed complex code tasks."""
MODEL_RTK_STANDARD: str = "gpt-3.5-turbo"
"""Standard model for RTK-routed non-code tasks."""

MODEL_MOA_REFERENCE: list[str] = [
    "openai/gpt-4o-mini",
    "anthropic/claude-3-5-haiku",
    "google/gemini-flash-1.5",
    "meta-llama/llama-3.3-70b-instruct",
]
"""Default reference models for Mixture-of-Agents ensemble."""


# ========================================================================
# Pricing table (cost_ledger.py)
# ========================================================================
MODEL_PRICE_CLAUDE_SONNET: str = "claude-sonnet-4-6"
MODEL_PRICE_CLAUDE_OPUS: str = "claude-opus-4-6"
MODEL_PRICE_CLAUDE_HAIKU: str = "claude-haiku-4-5"
MODEL_PRICE_GPT4O: str = "gpt-4o"
MODEL_PRICE_GPT4O_MINI: str = "gpt-4o-mini"
MODEL_PRICE_DEEPSEEK: str = "deepseek-chat"
