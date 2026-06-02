"""Centralized LLM model name references.

Every model is an explicit provider-qualified ID sourced from the
OpenRouter /v1/models API (2026-06-01).  ``openrouter/auto`` is FORBIDDEN.

Cascade (cost ignored — quality only):
  Tier 1: Owl Alpha (FREE, 1M ctx, agentic, tool use, 100k+ installed)
  Tier 2: Grok Build 0.1 (fast coding, agentic SWE workflows)
  Primary: Claude Opus 4.8 (Anthropic's most capable model)

Task-specific best picks:
  CODING:        Grok Build 0.1 — specialized agentic coding model
  FILE_OPS:      Gemini 3.1 Flash Lite — lowest latency, 1M context
  RESEARCH:      Kimi K2.6 — strong structured output
  REVIEW:        Claude Opus 4.8 — unmatched analysis
  PLANNING:      Owl Alpha — agentic, tool use, FREE
  SECURITY:      Claude Opus 4.8 — best vulnerability detection
  SUMMARIZATION: Gemini 3.1 Flash Lite — fast, coherent
  GENERAL:       Kimi K2.6 — strong all-rounder

Fallback chain: Owl Alpha → Grok Build 0.1 → Kimi K2.6 → Claude Opus 4.8
"""
from __future__ import annotations

# ========================================================================
# Executor Cascade (3-tier: agentic → coding → frontier)
# ========================================================================
MODEL_CASCADE_TIER1: str = "openrouter/owl-alpha"
"""First-attempt: Owl Alpha — FREE, 1M context, natively supports tool use, 100k+ installed on OpenRouter."""

MODEL_CASCADE_TIER2: str = "x-ai/grok-build-0.1"
"""Second-attempt: Grok Build 0.1 — fast coding model for agentic SWE workflows."""

MODEL_PRIMARY: str = "anthropic/claude-opus-4.8"
"""Primary fallback: Claude Opus 4.8 — Anthropic's most capable model, 1M context."""

# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "openrouter/owl-alpha"
"""Planning: Owl Alpha — agentic, tool use, strong at task decomposition."""

MODEL_CODE_REVIEW: str = "anthropic/claude-opus-4.8"
"""Code review: Claude Opus 4.8 — unmatched critique/analysis/bug-finding."""

MODEL_SUMMARIZE: str = "google/gemini-3.1-flash-lite"
"""Summary: Gemini 3.1 Flash Lite — fast, coherent, 1M context."""

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "openrouter/owl-alpha"
"""Default when no model is explicitly configured."""

MODEL_DI_SKILLOPT: str = "anthropic/claude-opus-4.8"
"""SkillOpt optimizer — needs strongest reasoning for skill improvement."""

MODEL_FACTORY_OPENAI: str = "gpt-4o-mini"
MODEL_FACTORY_ANTHROPIC: str = "anthropic/claude-opus-4.8"
MODEL_FACTORY_DEEPSEEK: str = "deepseek-chat"
MODEL_FACTORY_OPENROUTER: str = "openrouter/owl-alpha"
"""Factory defaults per provider."""

MODEL_DEFAULT_OPENAI: str = "gpt-4o-mini"
MODEL_DEFAULT_ANTHROPIC: str = "anthropic/claude-opus-4.8"
MODEL_DEFAULT_DEEPSEEK: str = "deepseek-chat"
MODEL_DEFAULT_OPENROUTER: str = "openrouter/owl-alpha"
"""Adapter constructor defaults."""

# ========================================================================
# Fallback chain
# ========================================================================
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    "openrouter/owl-alpha",              # Tier 1 — FREE, agentic
    "x-ai/grok-build-0.1",               # Tier 2 — fast coding
    "moonshotai/kimi-k2.6",              # Tier 3 — strong reasoning
    "anthropic/claude-opus-4.8",         # Primary — best quality
]

MODEL_FALLBACK_NON_OPENROUTER: str = "gpt-4o-mini"

# ========================================================================
# CQRS / deprecated
# ========================================================================
MODEL_COMMAND_DEFAULT: str = "openrouter/owl-alpha"
MODEL_DEPRECATED_AGENT: str = "openrouter/owl-alpha"
MODEL_DEPRECATED_TOOL_AGENT: str = "openrouter/owl-alpha"
MODEL_RTK_CHEAP: str = "openrouter/owl-alpha"
MODEL_RTK_PREMIUM: str = "anthropic/claude-opus-4.8"
MODEL_RTK_STANDARD: str = "openrouter/owl-alpha"

# ========================================================================
# Mixture-of-Agents ensemble
# ========================================================================
MODEL_MOA_REFERENCE: list[str] = [
    "openrouter/owl-alpha",
    "x-ai/grok-build-0.1",
    "qwen/qwen3.7-max",
    "moonshotai/kimi-k2.6",
]

# ========================================================================
# Pricing table (cost_ledger.py)
# ========================================================================
MODEL_PRICE_CLAUDE_SONNET: str = "claude-opus-4.8"
MODEL_PRICE_CLAUDE_OPUS: str = "claude-opus-4.8"
MODEL_PRICE_CLAUDE_HAIKU: str = "claude-haiku-latest"
MODEL_PRICE_GPT4O: str = "gpt-chat-latest"
MODEL_PRICE_GPT4O_MINI: str = "gpt-4o-mini"
MODEL_PRICE_KIMI: str = "kimi-k2.6"
MODEL_PRICE_DEEPSEEK: str = "deepseek-chat"
