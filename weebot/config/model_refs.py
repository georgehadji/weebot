"""Centralized LLM model name references.

Single source of truth for model strings.  Every OpenRouter model is
an explicit provider-qualified ID — ``openrouter/auto`` is FORBIDDEN
(it routes unpredictably and can select expensive models silently).

Model Selection Rationale (per-task):
  - Code Review: Claude Sonnet 4.6 — unmatched for critique, bug finding, architecture review
  - Planning: Kimi K2.6 — strong JSON-structured output, good at task decomposition
  - Executing (free): Qwen Coder Free — best free model for code/agent tasks, 1M context
  - Executing (budget): Kimi K2.6 — strong reasoning, good tool use, mid-cost
  - Executing (primary): Claude Sonnet 4.6 — best agentic tool use, longest autonomous horizon
  - Summarizing / Chat: Claude Sonnet 4.6 — clear concise output
  - Fallback chain: three explicit models, no auto-routing

Naming convention: ``MODEL_<PURPOSE>``.
"""
from __future__ import annotations

# ========================================================================
# Executor Cascade (3-tier: free → budget → primary)
# ========================================================================
MODEL_CASCADE_FREE: str = "qwen/qwen3-coder:free"
"""First-attempt: Qwen Coder Free — free, 1M context, strong for code/agents."""

MODEL_BUDGET: str = "moonshotai/kimi-k2.6"
"""Second-attempt: Kimi K2.6 — strong reasoning, good tool use, mid-cost."""

MODEL_PRIMARY: str = "anthropic/claude-sonnet-4.6"
"""Third-attempt / primary fallback: Claude Sonnet 4.6 — best agentic tool use."""

# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "moonshotai/kimi-k2.6"
"""Planning: Kimi K2.6 — strong task decomposition and JSON-structured output."""

MODEL_CODE_REVIEW: str = "anthropic/claude-sonnet-4.6"
"""Code review: Claude Sonnet 4.6 — unmatched critique/analysis/bug-finding."""

MODEL_SUMMARIZE: str = "anthropic/claude-sonnet-4.6"
"""Summary/Chat: Claude Sonnet 4.6 — clear, concise, accurate."""

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "moonshotai/kimi-k2.6"
"""Default when no model is explicitly configured (never auto)."""

MODEL_DI_SKILLOPT: str = "anthropic/claude-sonnet-4.6"
"""SkillOpt optimizer — needs strong reasoning for skill improvement."""

MODEL_FACTORY_OPENAI: str = "gpt-4o-mini"
MODEL_FACTORY_ANTHROPIC: str = "claude-3-5-sonnet-20241022"
MODEL_FACTORY_DEEPSEEK: str = "deepseek-chat"
MODEL_FACTORY_OPENROUTER: str = "moonshotai/kimi-k2.6"
"""Factory defaults per provider (used when model= param is omitted)."""

MODEL_DEFAULT_OPENAI: str = "gpt-4o-mini"
MODEL_DEFAULT_ANTHROPIC: str = "claude-3-5-sonnet-20241022"
MODEL_DEFAULT_DEEPSEEK: str = "deepseek-chat"
MODEL_DEFAULT_OPENROUTER: str = "moonshotai/kimi-k2.6"
"""Adapter constructor defaults."""

# ========================================================================
# Fallback chain (rate-limit recovery)
# ========================================================================
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    "qwen/qwen3-coder:free",            # free, always available
    "moonshotai/kimi-k2.6",             # cheap, strong
    "anthropic/claude-sonnet-4.6",      # premium, if budget allows
]
"""Fallback models tried in order on rate-limit (not auto-routed)."""

MODEL_FALLBACK_NON_OPENROUTER: str = "gpt-4o-mini"
"""Fallback when non-OpenRouter rate-limit is hit."""

# ========================================================================
# Free model pool (available for cascade experiments)
# ========================================================================
MODEL_CASCADE_FREE_GEMINI: str = "google/gemini-2.0-flash-exp:free"
MODEL_CASCADE_FREE_LLAMA: str = "meta-llama/llama-3.3-70b-instruct:free"
MODEL_CASCADE_FREE_NVIDIA: str = "nvidia/nemotron-3-super-120b-a12b:free"

# ========================================================================
# CQRS command defaults
# ========================================================================
MODEL_COMMAND_DEFAULT: str = "moonshotai/kimi-k2.6"

# ========================================================================
# Deprecated agents (legacy — frozen)
# ========================================================================
MODEL_DEPRECATED_AGENT: str = "moonshotai/kimi-k2.6"
MODEL_DEPRECATED_TOOL_AGENT: str = "moonshotai/kimi-k2.6"

# ========================================================================
# Router fallback strings (rtk_ai_router.py — legacy)
# ========================================================================
MODEL_RTK_CHEAP: str = "moonshotai/kimi-k2.6"
MODEL_RTK_PREMIUM: str = "anthropic/claude-sonnet-4.6"
MODEL_RTK_STANDARD: str = "moonshotai/kimi-k2.6"

# ========================================================================
# Mixture-of-Agents ensemble
# ========================================================================
MODEL_MOA_REFERENCE: list[str] = [
    "moonshotai/kimi-k2.6",
    "anthropic/claude-3-5-haiku",
    "google/gemini-2.0-flash-exp:free",
    "qwen/qwen3-coder:free",
]

# ========================================================================
# Pricing table (cost_ledger.py)
# ========================================================================
MODEL_PRICE_CLAUDE_SONNET: str = "claude-sonnet-4-6"
MODEL_PRICE_CLAUDE_OPUS: str = "claude-opus-4-6"
MODEL_PRICE_CLAUDE_HAIKU: str = "claude-haiku-4-5"
MODEL_PRICE_GPT4O: str = "gpt-4o"
MODEL_PRICE_GPT4O_MINI: str = "gpt-4o-mini"
MODEL_PRICE_KIMI: str = "kimi-k2.6"
MODEL_PRICE_DEEPSEEK: str = "deepseek-chat"
