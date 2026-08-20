"""Centralized LLM model name references.

9 allowed models — all explicit provider-qualified IDs.
``openrouter/auto`` is FORBIDDEN.

Cascade (2-tier direct API + 2-tier OpenRouter):
  Tier 1: Kimi K2.6 — via KIMI_API_KEY (direct), OpenRouter fallback
  Tier 2: DeepSeek V4 Flash — via DEEPSEEK_API_KEY (direct), OpenRouter fallback
  Tier 3: Grok Build 0.1 — fast coding, agentic SWE (OpenRouter)
  Tier 4: Qwen 3.8 Max — flagship coding, 1M ctx (OpenRouter)

Task-specific:
  CODING:        DeepSeek V4 Flash + Grok Build 0.1
  FILE_OPS:      DeepSeek V4 Flash
  RESEARCH:      Kimi K2.6 (direct API, structured output)
  REVIEW:        Grok 4.3 — reasoning, high factual accuracy
  PLANNING:      Kimi K2.6 (direct API, structured planning)
  SECURITY:      Grok 4.3 + DeepSeek V4 Flash — reasoning
  SUMMARIZATION: DeepSeek V4 Flash (fast, cheap)
  GENERAL:       Kimi K2.6 (direct API preferred)
"""

from __future__ import annotations

# ========================================================================
# Executor Cascade (4-tier)
# ========================================================================
MODEL_CASCADE_TIER1: str = "z-ai/glm-5.2"
"""Tier 1: GLM 5.2 — primary executor model.
1M context, long-horizon agent workflows, project-level SWE, strong coding.
Routed via OpenRouter (z-ai provider).  $1.20/$4.10 per 1M tokens."""

# ── Vision-capable models (VLM) ───────────────────────────────────
MODEL_VISION_PRIMARY: str = "openai/gpt-4o"
"""Primary VLM: GPT-4o — best multimodal, tool use, 128K context. $2.50/$10.00 per 1M."""

MODEL_VISION_FAST: str = "google/gemini-2.5-flash"
"""Gemini 2.5 Flash — fast VLM, strong vision, 1M context. Kept for backward compat."""

MODEL_VISION_FREE: str = "qwen/qwen2.5-vl-72b-instruct"
"""Budget VLM: Qwen2.5-VL 72B — open vision model, paid tier via OpenRouter. Use :free suffix only if credit-constrained."""

MODEL_BUDGET: str = "x-ai/grok-build-0.1"
"""Budget model for non-critical operations (compression, curation, defaults).
Same as Tier 1 — fast coding model via direct XAI_API_KEY."""

MODEL_CASCADE_TIER2: str = "deepseek/deepseek-v4-flash"
"""Tier 2: DeepSeek V4 Flash — fast fallback.
Direct API via DEEPSEEK_API_KEY (preferred). OpenRouter fallback.
Native model ID: ``deepseek-v4-flash`` (stripped by DeepSeekAdapter)."""

MODEL_CASCADE_TIER3: str = "moonshotai/kimi-k2.6"
"""Tier 3: Kimi K2.6 — structured output, broad knowledge, 256K context."""

MODEL_CASCADE_TIER4: str = "qwen/qwen3.8-max"
"""Tier 4: Qwen 3.8 Max — flagship agent-centric, coding strength, 1M context."""

# ═══════════════════════════════════════════════════════════════════════
# Additional model references — added 2026-07-21
# ═══════════════════════════════════════════════════════════════════════

MODEL_LONGCAT_2: str = "meituan/longcat-2.0"
"""LongCat 2.0 — back on OpenRouter catalog as of this check. 1M ctx, $0.30/$1.20.
Coding, repository-level changes, long-horizon problem solving, agentic."""

MODEL_INKLING: str = "thinkingmachines/inkling"
"""Inkling — verified present on OpenRouter API 2026-08-01. 1M ctx, $1/$4.05.
Image+audio understanding. General reasoning, coding, agentic, RAG."""

MODEL_INKLING_SMALL: str = "thinkingmachines/inkling-small"
"""Inkling Small — open-weight multimodal MoE, 12B active / 276B total.
512K ctx, $0.50/$1.20 per 1M. Text+image+audio input, tools, reasoning.
Cheaper, more efficient sibling of Inkling. No structured-output support."""

MODEL_QWEN_37_FLASH: str = "qwen/qwen3.7-flash"
"""Qwen 3.7 Flash — cheapest model in the catalog, $0.03/$0.13 per 1M.
1M ctx, 64K output, vision-language (text/image/video), tools + structured output.
Ideal for high-volume routing, classification, and inner-loop decisions."""

MODEL_DEEPSEEK_V4_FLASH_0731: str = "deepseek/deepseek-v4-flash-0731"
"""DeepSeek V4 Flash 0731 — re-post-trained V4 Flash revision, $0.14/$0.28 per 1M.
1M ctx, 384K max output (vs 160K on base V4 Flash), same price. Coding, reasoning, agents."""

MODEL_MUSE_SPARK: str = "meta/muse-spark-1.1"
"""Muse Spark 1.1 — back on OpenRouter catalog as of this check. 1M ctx, $1.25/$4.25.
Multi-agent orchestration, MCP, zero-shot tool use, structured output. US-only."""

MODEL_KIMI_K3: str = "moonshotai/kimi-k3"
"""Kimi K3 — back on OpenRouter catalog as of this check. 1M ctx, $3/$15.
Complex coding, large-repo navigation, tool use, image/log debugging."""

# ═══════════════════════════════════════════════════════════════════════
# Additional model references — added 2026-07-21
# ═══════════════════════════════════════════════════════════════════════

MODEL_LAGUNA_XS_21: str = "poolside/laguna-xs-2.1"
"""Laguna XS 2.1 — Poolside coding agent, 1M ctx, $0.09/$0.18 (OpenRouter, verified).
Extremely cheap agentic coding."""

MODEL_LAGUNA_S_21: str = "poolside/laguna-s-2.1"
"""Laguna S 2.1 — back on OpenRouter catalog as of this check, 1M ctx, $0.09/$0.18.
Larger sibling of Laguna XS 2.1. Agentic coding."""

MODEL_GEMINI_35_FLASH_LITE: str = "google/gemini-3.5-flash-lite"
"""Gemini 3.5 Flash-Lite — back on OpenRouter catalog as of this check, 1M ctx, $0.30/$2.50.
Upgraded agentic capabilities. Subagents, focused multi-agent tasks."""

MODEL_GEMINI_36_FLASH: str = "google/gemini-3.6-flash"
"""Gemini 3.6 Flash — back on OpenRouter catalog as of this check, 1M ctx, $1.50/$7.50.
Coding, agentic workflows, web/app dev. Polished output, fewer edits, reduced token use."""

# ═══════════════════════════════════════════════════════════════════════
# Verbalized Sampling
# ═══════════════════════════════════════════════════════════════════════
MODEL_VS_CAPABLE: str = MODEL_CASCADE_TIER4
"""VS-capable model: same as Tier 4 (Qwen 3.8 Max). Paper: larger models benefit more."""

MODEL_VS_FALLBACK: str = "x-ai/grok-build-0.1"
"""VS fallback when Tier 4 unavailable."""


def get_vs_model() -> str:
    """Return the single source of truth for the VS-capable model."""
    return MODEL_VS_CAPABLE


# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "z-ai/glm-5.2:thinking"
"""Planning: GLM 5.2 :thinking — reasoning model (effort=xhigh), 1M context, Design Arena #1 coding. $0.95/$3.00 per 1M."""

MODEL_CODE_REVIEW: str = "x-ai/grok-4.3"
"""Code review: Grok 4.3 — reasoning model, high factual accuracy, 1M context."""

MODEL_SUMMARIZE: str = "deepseek/deepseek-v4-flash"
"""Summary: DeepSeek V4 Flash — fast, cheap, good summarization via DEEPSEEK_API_KEY."""

# ========================================================================
# Web Search — Perplexity Sonar models (via OpenRouter)
# ========================================================================
MODEL_SEARCH_PERPLEXITY_SONAR: str = "perplexity/sonar"
"""Primary web search: Sonar — lightweight, fast, search-grounded with citations.
$1/$1 per 1M tokens, 127K context. Returns search_results + citations alongside prose."""

MODEL_SEARCH_PERPLEXITY_SONAR_FALLBACK: str = "perplexity/sonar-pro"
"""Fallback web search: Sonar Pro — deeper multi-step queries, 2× citations.
$3/$15 per 1M tokens, 200K context. Use when Sonar returns insufficient results."""

# ========================================================================
# KwaiPilot KAT-Coder Models (via OpenRouter)
# ========================================================================
MODEL_KWAIPILOT_KAT_CODER_PRO: str = "kwaipilot/kat-coder-pro-v2.5"
"""KwaiPilot KAT-Coder-Pro V2.5 — enterprise-grade agentic coding model."""

MODEL_KWAIPILOT_KAT_CODER_AIR: str = "kwaipilot/kat-coder-air-v2.5"
"""KwaiPilot KAT-Coder-Air V2.5 — high-speed, cost-efficient agentic coding model."""

# ========================================================================
# Per-Agent (Role) Model Selection
# ========================================================================
MODEL_ROLE_RESEARCHER: str = "x-ai/grok-build-0.1"
"""Researcher: Grok Build 0.1 via XAI_API_KEY — fast coding, broad knowledge, source synthesis."""

MODEL_ROLE_ANALYST: str = "deepseek/deepseek-v4-flash"
"""Analyst: DeepSeek V4 Flash via DEEPSEEK_API_KEY — fast math/reasoning, complex data analysis."""

MODEL_ROLE_CODER: str = "deepseek/deepseek-v4-flash"
"""Coder: DeepSeek V4 Flash — fast coding, low latency via DEEPSEEK_API_KEY."""

MODEL_ROLE_REVIEWER: str = "x-ai/grok-4.3"
"""Reviewer: Grok 4.3 — highest factual accuracy, reasoning, security audit."""

MODEL_ROLE_ADMIN: str = "x-ai/grok-build-0.1"
"""Admin: Kimi K2.6 via KIMI_API_KEY — orchestrates sub-agents, decomposes complex tasks."""

MODEL_ROLE_AUTOMATION: str = "deepseek/deepseek-v4-flash"
"""Automation: DeepSeek V4 Flash via DEEPSEEK_API_KEY — instruction following, reliable execution."""

MODEL_ROLE_DOCUMENTATION: str = "deepseek/deepseek-v4-flash"
"""Documentation: DeepSeek V4 Flash — fast, cheap, good for writing/formatting."""

# ── Role → Model cascade lookup (primary + 2 fallbacks) ────────────

_ROLE_MODEL_CASCADE: dict[str, list[str]] = {
    "researcher": [
        "moonshotai/kimi-k2.6:thinking",  # primary: Kimi K2.6 :thinking — multi-source CoT synthesis
        "deepseek/deepseek-v4-flash:thinking",  # fallback 1: DeepSeek V4 Flash :thinking — fast reasoning
        "qwen/qwen3.8-max",  # fallback 2: Qwen Max — strong comprehension
    ],
    "analyst": [
        "deepseek/deepseek-v4-flash:thinking",  # primary: DeepSeek V4 Flash :thinking — math/reasoning
        "moonshotai/kimi-k2.6:thinking",  # fallback 1: Kimi K2.6 :thinking
        "x-ai/grok-4.3:thinking",  # fallback 2: Grok 4.3 :thinking — factual accuracy
    ],
    "coder": [
        "x-ai/grok-build-0.1",  # primary: Grok Build — fast agentic SWE
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 1: KAT-Coder-Pro
        "poolside/laguna-xs-2.1",  # fallback 2: Laguna XS 2.1 — coding
        "kwaipilot/kat-coder-air-v2.5",  # fallback 3: KAT-Coder-Air
        "minimax/minimax-m3",  # fallback 4: MiniMax M3 — budget
        "deepseek/deepseek-v4-flash",  # fallback 4: DeepSeek V4 Flash
        "moonshotai/kimi-k2.6",  # fallback 5: Kimi K2.6
        "moonshotai/kimi-k2.7-code",  # fallback 6: Kimi K2.7 Code — complex coding
    ],
    "executor": [
        "z-ai/glm-5.2:thinking",  # primary: GLM 5.2 :thinking
        "google/gemini-3.5-flash",  # fallback 1: Gemini 3.5 Flash — 1M ctx
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 2: KAT-Coder-Pro V2.5 — enterprise-grade agentic coding model
        "kwaipilot/kat-coder-air-v2.5",  # fallback 2: KAT-Coder-Air V2.5 — high-speed, cost-efficient agentic coding
        "deepseek/deepseek-v4-flash:thinking",  # fallback 3: DeepSeek V4 Flash :thinking — fast reasoning
        "moonshotai/kimi-k2.6:thinking",  # fallback 4: Kimi K2.6 :thinking — structured + CoT
    ],
    "reviewer": [
        "x-ai/grok-4.3:thinking",  # primary: Grok 4.3 :thinking
        "google/gemini-2.5-flash",  # fallback 1: Gemini 2.5 Flash — multimodal
        "deepseek/deepseek-v4-flash:thinking",  # fallback 2: DeepSeek V4 Flash :thinking
        "moonshotai/kimi-k2.6:thinking",  # fallback 3: Kimi K2.6 :thinking
    ],
    "admin": [
        "x-ai/grok-4.3",  # primary: Grok 4.3 — agentic orchestration
        "x-ai/grok-build-0.1",  # fallback 1: Grok Build
        "x-ai/grok-4.3",  # fallback 2: Grok 4.3
        "moonshotai/kimi-k2.6",  # fallback 3: Kimi K2.6
    ],
    "automation": [
        "x-ai/grok-build-0.1",  # primary: Grok Build — fast agentic SWE
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 1: KAT-Coder-Pro V2.5 — enterprise-grade agentic coding model
        "kwaipilot/kat-coder-air-v2.5",  # fallback 2: KAT-Coder-Air V2.5 — high-speed, cost-efficient agentic coding
        "deepseek/deepseek-v4-flash",  # fallback 3: DeepSeek V4 Flash — instruction following
        "moonshotai/kimi-k2.6",  # fallback 4: Kimi K2.6
    ],
    "documentation": [
        "deepseek/deepseek-v4-flash",  # primary: DeepSeek V4 Flash — fast, cheap
        "moonshotai/kimi-k2.6",  # fallback 1: Kimi K2.6
        "minimax/minimax-m3",  # fallback 2: MiniMax M3
    ],
    "product_manager": [
        "moonshotai/kimi-k2.6",
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 1: KAT-Coder-Pro V2.5 — enterprise-grade agentic coding
        "kwaipilot/kat-coder-air-v2.5",  # fallback 2: KAT-Coder-Air V2.5 — high-speed, cost-efficient agentic coding
        "deepseek/deepseek-v4-flash",
        "minimax/minimax-m3",
    ],
    "planner": [
        "moonshotai/kimi-k2.6:thinking",  # primary: Kimi K2.6 :thinking — structured planning + CoT
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 1: KAT-Coder-Pro V2.5 — enterprise-grade agentic coding
        "kwaipilot/kat-coder-air-v2.5",  # fallback 2: KAT-Coder-Air V2.5 — high-speed, cost-efficient agentic coding
        "deepseek/deepseek-v4-flash:thinking",  # fallback 3: DeepSeek V4 Flash :thinking
        "x-ai/grok-build-0.1",  # fallback 4: Grok Build — agentic
    ],
    "planner_sub": [
        "moonshotai/kimi-k2.6:thinking",
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 1: KAT-Coder-Pro V2.5
        "kwaipilot/kat-coder-air-v2.5",  # fallback 2: KAT-Coder-Air V2.5
        "deepseek/deepseek-v4-flash:thinking",
        "x-ai/grok-build-0.1",
    ],
    "designer": [
        "deepseek/deepseek-v4-flash",  # primary: fast, cheap
        "kwaipilot/kat-coder-pro-v2.5",  # fallback 1: KAT-Coder-Pro V2.5 — layout & visual design experts
        "kwaipilot/kat-coder-air-v2.5",  # fallback 2: KAT-Coder-Air V2.5
        "moonshotai/kimi-k2.6",
        "minimax/minimax-m3",  # fallback 4: MiniMax M3 — paid, $0.30/$1.20
    ],
    "vision": [
        "openai/gpt-4o",  # primary: best vision + tool use
        "google/gemini-3.5-flash",  # fallback 1: 1M ctx
        "qwen/qwen3.7-flash",  # fallback 2: text/image/video, 1M ctx, $0.03/1M
        "thinkingmachines/inkling-small",  # fallback 3: text/image/audio MoE, 512K ctx
        "google/gemini-2.5-flash",  # fallback 4: Gemini 2.5 Flash — multimodal
        "qwen/qwen2.5-vl-72b-instruct",  # fallback 5: budget VLM
    ],
}


def get_model_cascade_for_role(role: str | None) -> list[str]:
    """Return the model cascade (primary + 2 fallbacks) for an agent role.

    Args:
        role: Agent role name (e.g. \"coder\", \"researcher\").
              ``None`` or unknown roles fall back to the default cascade.

    Returns:
        List of 3 OpenRouter-qualified model IDs: [primary, fallback1, fallback2].
    """
    if role and role in _ROLE_MODEL_CASCADE:
        return list(_ROLE_MODEL_CASCADE[role])
    # Default cascade — prefer xAI (native API key) over OpenRouter models
    return ["x-ai/grok-build-0.1", "x-ai/grok-4.3", MODEL_CASCADE_TIER1]


# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "x-ai/grok-build-0.1"
MODEL_DI_SKILLOPT: str = "x-ai/grok-4.3"

MODEL_FACTORY_OPENAI: str = "moonshotai/kimi-k2.6"
MODEL_FACTORY_ANTHROPIC: str = "qwen/qwen3.8-max"
MODEL_FACTORY_DEEPSEEK: str = "deepseek/deepseek-v4-flash"
MODEL_FACTORY_OPENROUTER: str = "moonshotai/kimi-k2.6"

MODEL_DEFAULT_OPENAI: str = "moonshotai/kimi-k2.6"
MODEL_DEFAULT_ANTHROPIC: str = "qwen/qwen3.8-max"
MODEL_DEFAULT_DEEPSEEK: str = "deepseek/deepseek-v4-flash"
MODEL_DEFAULT_OPENROUTER: str = "moonshotai/kimi-k2.6"

# ========================================================================
# Fallback chain
# ========================================================================
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.6",
    "deepseek/deepseek-v4-flash",
    "x-ai/grok-build-0.1",
    "qwen/qwen3.8-max",
    "x-ai/grok-4.3",
    "kwaipilot/kat-coder-pro-v2.5",
    "kwaipilot/kat-coder-air-v2.5",
    "minimax/minimax-m3",
    "deepseek/deepseek-v4-flash-0731",  # 1M ctx / 384K out, same price as base V4 Flash
    "qwen/qwen3.7-flash",  # cheapest fallback of last resort
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
MODEL_RTK_STANDARD: str = "qwen/qwen3.8-max"

# ========================================================================
# Image Generation Models (text → image via OpenRouter)
# ========================================================================
MODEL_IMAGE_FREE: str = "black-forest-labs/flux.2-klein-4b"
"""Budget image generation: Flux.2 Klein 4B — cheapest paid, fast, decent quality."""

MODEL_IMAGE_FAST: str = "black-forest-labs/flux.2-flex"
"""Fast image generation: Flux.2 Flex — batch-optimized, fast throughput."""

MODEL_IMAGE_VECTOR: str = "recraft/recraft-v4.1-pro-vector"
"""Professional vector/SVG generation: Recraft V4.1 Pro Vector — logos, icons, brand assets."""

MODEL_IMAGE_PHOTOREALISTIC: str = "black-forest-labs/flux.2-pro"
"""Photorealistic image generation: Flux.2 Pro — highest quality photorealism."""

MODEL_IMAGE_WEBSITE: str = "google/gemini-2.5-flash-image"
"""DEPRECATED: Gemini 2.5 Flash Image — use google/gemini-3.1-flash-lite for general-purpose vision tasks.
Website image generation: diagrams, UI mockups, illustrations. Kept for backward compat."""

# ── New image models — added 2026-07-21 ──────────────────────────
MODEL_IMAGE_KREA_LARGE: str = "krea/krea-2-large"
"""Krea 2 Large — high-capability image gen, $0.06/img. 2x Krea 2 Medium.
Raw, textured, photorealistic, expressive artistic styles, motion blur, grain."""

MODEL_IMAGE_KREA_MEDIUM_TURBO: str = "krea/krea-2-medium-turbo"
"""Krea 2 Medium Turbo — speed-focused distilled image gen, $0.015/img.
Rapid iteration, graphic design exploration, fast generation priority."""

MODEL_IMAGE_KREA_MEDIUM: str = "krea/krea-2-medium"
"""Krea 2 Medium — balanced, cost-efficient image gen, $0.03/img.
Illustration, anime, painting, expressive artistic styles. Stable, consistent."""

MODEL_IMAGE_IDEOGRAM: str = "ideogram/ideogram-v3-turbo"
"""Ideogram 3.0 Turbo — best text rendering, logos, branding, typography ($0.03/img)."""

MODEL_IMAGE_QWEN: str = "qwen/qwen-image-3"
"""Qwen Image 3 — unified image generation and editing, $0.03/img (added 2026-08-05).
66K context. Precise text rendering down to 10px, enhanced world knowledge."""

MODEL_IMAGE_QWEN_PRO: str = "qwen/qwen-image-3-pro"
"""Qwen Image 3 Pro — premium tier of Qwen Image 3, $0.04/img (added 2026-08-05).
66K context. Precise text/detail rendering down to 10px, richer world knowledge."""


def get_image_models() -> list[str]:
    """Return the canonical list of image generation model IDs."""
    return [
        "black-forest-labs/flux.2-pro",
        "black-forest-labs/flux.2-flex",
        "black-forest-labs/flux.2-klein-4b",
        "recraft/recraft-v4.1-pro-vector",
        "recraft/recraft-v4.1-pro",
        "google/gemini-2.5-flash-image",
        "x-ai/grok-imagine-image-quality",
        "bytedance-seed/seedream-4.5",
        "microsoft/mai-image-2.5",
        "ideogram/ideogram-v3-turbo",
        "ideogram/ideogram-v3-default",
        "ideogram/ideogram-v4-turbo",
        "qwen/qwen-image-3",
        "qwen/qwen-image-3-pro",
    ]


# ========================================================================
# Image Generation Cascade — use-case → primary → fallback → free → SVG
# ========================================================================

IMAGE_CASCADE: dict[str, list[str]] = {
    # ── Website hero banners — photorealistic, high impact ──────────
    "hero": [
        "x-ai/grok-imagine-image-quality",  # 1st: cheap (~$0.05/img) — direct xAI
        "black-forest-labs/flux.2-pro",  # 2nd: paid — photorealistic
        "black-forest-labs/flux.2-max",  # 3rd: paid — max quality
    ],
    # ── Logos, brand assets, icons — vector output preferred ────────
    "logo": [
        "ideogram/ideogram-v3-turbo",  # 1st: paid — best text/logo rendering
        "recraft/recraft-v4.1-pro-vector",  # 2nd: paid — professional SVG
        "recraft/recraft-v4.1-pro",  # 3rd: paid — raster fallback
    ],
    # ── Small icons, favicons, UI elements ──────────────────────────
    "icon": [
        "krea/krea-2-medium-turbo",  # 1st: $0.015/img — fastest iteration
        "black-forest-labs/flux.2-klein-4b",  # 2nd: cheapest paid — fast
        "recraft/recraft-v4.1-pro-vector",  # 3rd: paid — clean vector
        "black-forest-labs/flux.2-flex",  # 4th: paid — batch-optimized
    ],
    # ── Photorealistic — products, people, places ───────────────────
    "photo": [
        "x-ai/grok-imagine-image-quality",  # 1st: cheap (~$0.05/img) — direct xAI
        "black-forest-labs/flux.2-pro",  # 2nd: paid — excellent quality
        "krea/krea-2-large",  # 3rd: raw, textured photorealism — $0.06/img
        "black-forest-labs/flux.2-max",  # 5th: paid — max quality
        "recraft/recraft-v4.1-pro",  # 5th: paid — consistent output
    ],
    # ── Diagrams, charts, UI mockups, technical illustrations ───────
    "diagram": [
        "krea/krea-2-medium-turbo",  # 1st: $0.015/img — cheap+fast
        "google/gemini-2.5-flash-image",  # 2nd: cheap — specialized
        "recraft/recraft-v4.1-pro-vector",  # 3rd: paid — vector output
    ],
    # ── Social media, thumbnails — fast, cheap, decent ──────────────
    "social": [
        "krea/krea-2-medium-turbo",  # 1st: $0.015/img — cheapest, fastest
        "krea/krea-2-medium",  # 2nd: balanced artistic
        "krea/krea-2-medium",  # 3rd: balanced artistic — $0.03/img
        "black-forest-labs/flux.2-klein-4b",  # 6th: cheapest paid — fast
        "black-forest-labs/flux.2-flex",  # 6th: batch-optimized
        "x-ai/grok-imagine-image-quality",  # 6th: cheap (~$0.05/img) — direct xAI
    ],
    # ── Text-heavy images — signs, banners with text ────────────────
    "text": [
        "ideogram/ideogram-v3-turbo",  # 1st: paid — industry-leading text rendering
        "recraft/recraft-v4.1-pro-vector",  # 2nd: paid — vector text
        "bytedance-seed/seedream-4.5",  # 3rd: paid — best text rendering
        "qwen/qwen-image-3",  # 4th: paid — precise text rendering down to 10px
    ],
    # ── Branded / enterprise — safety, consistency ──────────────────
    "brand": [
        "ideogram/ideogram-v3-turbo",  # 1st: paid — brand-accurate text + logos
        "recraft/recraft-v4.1-pro",  # 2nd: paid — consistent output
        "microsoft/mai-image-2.5",  # 3rd: paid — enterprise safety
    ],
    # ── General / catch-all ────────────────────────────────────────
    "general": [
        "x-ai/grok-imagine-image-quality",  # 1st: cheap (~$0.05/img) — direct xAI
        "black-forest-labs/flux.2-pro",  # 2nd: paid — photorealistic
        "krea/krea-2-large",  # 3rd: raw photorealism — $0.06/img
        "krea/krea-2-medium",  # 4th: balanced artistic — $0.03/img
        "black-forest-labs/flux.2-flex",  # 5th: paid — batch-optimized
        "qwen/qwen-image-3-pro",  # 6th: paid — unified gen+edit, 66K ctx, $0.04/img
    ],
}


def get_image_model_for(use_case: str, tier: int = 0, free_only: bool = False) -> str:
    """Return the best image model for *use_case* at the given cascade tier.

    Args:
        use_case: One of 'hero', 'logo', 'icon', 'photo', 'diagram',
                  'social', 'text', 'brand', 'general'.
        tier: 0 = primary, 1 = first fallback, 2 = second fallback, etc.
        free_only: Deprecated — all models are now paid. Returns tier 0.

    Returns:
        Model ID string, or the SVG template fallback marker 'svg:hero',
        'svg:logo', etc. when no API model is appropriate.

    Raises:
        KeyError: If *use_case* is not recognized.
    """
    cascade = IMAGE_CASCADE.get(use_case, IMAGE_CASCADE["general"])
    if free_only:
        # No free models remain; return the cheapest paid option (tier 0)
        return cascade[0] if cascade else "svg:" + use_case
    if tier < len(cascade):
        return cascade[tier]
    return cascade[-1]  # clamp to last available


def describe_image_cascade(use_case: str) -> str:
    """Return a human-readable description of the cascade for *use_case*."""
    cascade = IMAGE_CASCADE.get(use_case, IMAGE_CASCADE["general"])
    labels = ["Primary", "Fallback 1", "Fallback 2", "Fallback 3", "Fallback 4"]
    lines = [
        f"  {labels[i] if i < len(labels) else f'Tier {i}'}: {m}" for i, m in enumerate(cascade)
    ]
    lines.append(f"  Ultimate: SVG template ({use_case})")
    return "\n".join(lines)


# ========================================================================
# Video Generation Models (text → video via OpenRouter)
# ========================================================================

MODEL_VIDEO_XAI: str = "x-ai/grok-imagine-video"
"""xAI Grok Imagine Video v1 — image-to-video gen. Original version."""

MODEL_VIDEO_XAI_15: str = "x-ai/grok-imagine-video-1.5"
"""xAI Grok Imagine Video 1.5 — $0.08/sec. Image-to-video with sync
sound effects, ambience, dialogue. Animates starting image with text prompt."""
"""xAI Grok Imagine Video — from $0.05/video. Direct xAI API path available."""

MODEL_VIDEO_KLING_PRO: str = "kling/video-v3-pro"
"""Kling Video v3.0 Pro — from $0.168/video. High quality, Kwaivgi platform."""

MODEL_VIDEO_KLING_STANDARD: str = "kling/video-v3-standard"
"""Kling Video v3.0 Standard — from $0.126/video. Faster, lower cost."""

MODEL_VIDEO_VEO_FAST: str = "google/veo-3.1-fast"
"""Google Veo 3.1 Fast — from $0.10/video. Fast inference."""

MODEL_VIDEO_VEO_LITE: str = "google/veo-3.1-lite"
"""Google Veo 3.1 Lite — from $0.05/video. Budget option."""

MODEL_VIDEO_KLING_O1: str = "kling/video-o1-pro"
"""Kling Video O1 Pro — $0.112/video. Reasoning-enhanced quality."""

MODEL_VIDEO_HAILUO: str = "minimax/hailuo-2.3"
"""MiniMax Hailuo 2.3 — $0.082/video. Strong cinematic output."""

MODEL_VIDEO_SEEDANCE_2: str = "bytedance/seedance-2.0"
"""ByteDance Seedance 2.0 — from $0.067/video."""

MODEL_VIDEO_SEEDANCE_2_FAST: str = "bytedance/seedance-2.0-fast"
"""ByteDance Seedance 2.0 Fast — from $0.054/video."""

MODEL_VIDEO_WAN_27: str = "alibaba/wan-2.7"
"""Alibaba Wan 2.7 — from $0.10/video. Good general quality."""

MODEL_VIDEO_WAN_26: str = "alibaba/wan-2.6"
"""Alibaba Wan 2.6 — from $0.04/video. Budget option."""

MODEL_VIDEO_SEEDANCE_15: str = "bytedance/seedance-1.5-pro"
"""ByteDance Seedance 1.5 Pro — from $0.023/video. Cheapest option."""

MODEL_VIDEO_SORA_2: str = "openai/sora-2-pro"
"""OpenAI Sora 2 Pro — from $0.30/video. Premium quality."""

MODEL_VIDEO_VEO_31: str = "google/veo-3.1"
"""Google Veo 3.1 — from $0.40/video. Highest quality."""


def get_video_models() -> list[str]:
    """Return the canonical list of video generation model IDs."""
    return [
        "x-ai/grok-imagine-video",
        "kling/video-v3-pro",
        "kling/video-v3-standard",
        "google/veo-3.1-fast",
        "google/veo-3.1-lite",
        "kling/video-o1-pro",
        "minimax/hailuo-2.3",
        "bytedance/seedance-2.0",
        "bytedance/seedance-2.0-fast",
        "alibaba/wan-2.7",
        "alibaba/wan-2.6",
        "bytedance/seedance-1.5-pro",
        "openai/sora-2-pro",
        "google/veo-3.1",
    ]


# ========================================================================
# Video Generation Cascade — use case → primary → fallback → placeholder
# ========================================================================

VIDEO_CASCADE: dict[str, list[str]] = {
    # ── Short / social clips — fast, cheap, decent ──────────────
    "short": [
        "bytedance/seedance-2.0-fast",  # 1st: fast + cheap
        "bytedance/seedance-2.0",  # 2nd: better quality
        "kling/video-v3-standard",  # 3rd: standard quality
    ],
    # ── Cinematic / narrative — quality first ───────────────────
    "cinematic": [
        "openai/sora-2-pro",  # 1st: premium
        "google/veo-3.1",  # 2nd: highest quality Google
        "minimax/hailuo-2.3",  # 3rd: strong cinematic
        "kling/video-v3-pro",  # 4th: pro quality
    ],
    # ── Product demos / marketing ───────────────────────────────
    "product": [
        "alibaba/wan-2.7",  # 1st: good general
        "kling/video-v3-pro",  # 2nd: pro quality
        "google/veo-3.1-fast",  # 3rd: fast
    ],
    # ── Brand / enterprise — safety, consistency ────────────────
    "brand": [
        "x-ai/grok-imagine-video-1.5",  # 1st: direct xAI — v1.5 with audio
        "x-ai/grok-imagine-video",  # 2nd: direct xAI — v1 fallback
        "google/veo-3.1",  # 3rd: professional
        "kling/video-o1-pro",  # 4th: reasoning-enhanced
    ],
    # ── General / catch-all — free → cheap → best ──────────────
    "general": [
        "x-ai/grok-imagine-video-1.5",  # 1st: direct xAI — v1.5 with audio
        "x-ai/grok-imagine-video",  # 2nd: direct xAI — v1 fallback
        "kling/video-v3-standard",  # 3rd: standard
        "alibaba/wan-2.6",  # 4th: budget
        "google/veo-3.1-lite",  # 5th: lite
    ],
}


def get_video_model_for(use_case: str, tier: int = 0) -> str:
    """Return the best video model for *use_case* at the given cascade tier.

    Args:
        use_case: One of 'short', 'cinematic', 'product', 'brand', 'general'.
        tier: 0 = primary, 1 = first fallback, 2 = second fallback, etc.

    Returns:
        Model ID string.

    Raises:
        KeyError: If *use_case* is not recognized.
    """
    cascade = VIDEO_CASCADE.get(use_case, VIDEO_CASCADE["general"])
    if tier < len(cascade):
        return cascade[tier]
    return cascade[-1]  # clamp to last available


# ========================================================================
# Mixture-of-Agents
# ========================================================================
MODEL_MOA_REFERENCE: list[str] = [
    "moonshotai/kimi-k2.6",
    "deepseek/deepseek-v4-flash",
    "x-ai/grok-build-0.1",
    "qwen/qwen3.8-max",
]

# ========================================================================
# Pricing table
# ========================================================================
MODEL_PRICE_CLAUDE_SONNET: str = "qwen/qwen3.8-max"
MODEL_PRICE_CLAUDE_OPUS: str = "x-ai/grok-4.3"
MODEL_PRICE_CLAUDE_HAIKU: str = "minimax/minimax-m3"
MODEL_PRICE_GPT4O: str = "qwen/qwen3.8-max"
MODEL_PRICE_GPT4O_MINI: str = "minimax/minimax-m3"
MODEL_PRICE_KIMI: str = "minimax/minimax-m3"
MODEL_PRICE_DEEPSEEK: str = "deepseek/deepseek-v4-flash"


# ═══════════════════════════════════════════════════════════════════════
# Per-Model Harness Resolution
# ═══════════════════════════════════════════════════════════════════════


def sanitize_model_id(model_id: str) -> str:
    """Sanitize a model ID for use as a filename.

    Model IDs from OpenRouter contain ``/`` and sometimes ``:``
    (e.g. ``"z-ai/glm-5.2"`` or ``"deepseek/deepseek-v4-flash:thinking"``).
    These are replaced with ``_`` to produce valid filenames.
    """
    return model_id.replace("/", "_").replace(":", "_")


def get_harness_for_model(model_id: str) -> str:
    """Return the path to the per-model harness config for *model_id*.

    Returns the per-model variant path if it exists; otherwise falls
    back to the default shared harness.  This lets the Self-Harness
    loop tune harnesses independently per model.

    Args:
        model_id: e.g. ``"z-ai/glm-5.2"`` or ``"deepseek/deepseek-v4-flash"``.

    Returns:
        Relative path to the YAML harness config file.
    """
    from pathlib import Path

    safe_name = sanitize_model_id(model_id)
    model_file = Path(f"weebot/config/harness/models/{safe_name}.yaml")
    if model_file.exists():
        return str(model_file)
    return "weebot/config/harness/v0.2.0.yaml"


# ========================================================================
# Free-tier models (canonical list)
# ========================================================================


def get_free_models() -> list[str]:
    """Return the canonical list of budget (paid) model IDs.

    Previously returned free-tier models; now returns cheapest paid alternatives.
    Verified against OpenRouter API 2026-06.
    """
    return [
        "deepseek/deepseek-v4-flash",
        "qwen/qwen3-coder-30b-a3b-instruct",
        "openai/gpt-4.1-nano",
        "minimax/minimax-m3",
        "meta-llama/llama-4-scout",
        "nex-agi/nex-n2-pro",
    ]


# ========================================================================
# Rerank Models (Cohere via OpenRouter — text->rerank modality)
# ========================================================================
# These are NOT chat models. They use a dedicated rerank endpoint
# (POST /rerank) proxied by OpenRouter.  They cannot be called via
# LLMPort.chat().  A dedicated RerankPort + adapter is required.
# See docs/plans/rerank-integration.md for the integration plan.

RERANK_MODEL_PRO: str = "cohere/rerank-4-pro"
"""Cohere Rerank 4 Pro — 32K context, 100+ languages, $0.0025/search.
Best quality. Use for high-value reranking: multi-source research synthesis,
skill retrieval, staged evaluator probe ordering."""

RERANK_MODEL_FAST: str = "cohere/rerank-4-fast"
"""Cohere Rerank 4 Fast — 32K context, 100+ languages, lower latency/cost.
Use for latency-sensitive paths: web search result reordering,
conversation compressor turn selection."""

RERANK_MODEL_FREE: str = "cohere/rerank-4-fast"
"""Cohere Rerank 4 Fast — cheapest paid rerank, 32K context, 100+ languages.
Use for high-throughput, low-criticality paths (search, memory, knowledge graph).
NOTE: Not confirmed against the Cohere-compatible rerank endpoint.  The
adapter falls back to RERANK_MODEL_VERIFIED if this model returns a non-200
response."""

RERANK_MODEL_V35: str = "cohere/rerank-v3.5"
"""Cohere Rerank v3.5 — 4K context, 100+ languages, lowest cost.
Use for high-throughput paths: memory archivist event scoring,
knowledge graph FTS5 result reordering."""

RERANK_MODEL_VERIFIED: str = "cohere/rerank-v3.5"
"""Verified to work with OpenRouter POST /v1/rerank (Cohere-compatible interface).
Fallback model used when the primary rerank model returns a non-200 response.
Identical to RERANK_MODEL_V35 — kept as a separate semantic constant so
infrastructure code can reference the verified-fallback concept explicitly."""


def get_rerank_model_for(use_case: str) -> str:
    """Return the recommended rerank model for a given use case.

    Args:
        use_case: One of 'research', 'search', 'skills', 'memory',
                  'evaluation', 'knowledge'.

    Returns:
        OpenRouter-qualified model ID.
    """
    _rerank_map = {
        "research": RERANK_MODEL_PRO,  # multi-source synthesis — quality matters
        "skills": RERANK_MODEL_PRO,  # BM25 → semantic — quality matters
        "evaluation": RERANK_MODEL_PRO,  # staged evaluator — quality matters
        "search": RERANK_MODEL_FREE,  # web search — high-throughput, free tier
        "compressor": RERANK_MODEL_FREE,  # conversation compressor — high-throughput
        "memory": RERANK_MODEL_FREE,  # memory archivist — high-throughput
        "knowledge": RERANK_MODEL_FREE,  # knowledge graph FTS5 — high-throughput
    }
    return _rerank_map.get(use_case, RERANK_MODEL_FREE)


def get_models_for_role_and_task(
    role: str, task_type: str = "", cascade: list[str] | None = None
) -> list[str]:
    """Return the combined model list for a role + optional task type.

    Merges ``_ROLE_MODEL_CASCADE`` (role-based) and ``MODEL_CASCADE``
    (task-based) into a single deduplicated list. Role models come first
    (they're specific to the agent), then task models (general-purpose).

    Args:
        role: Agent role name (e.g. ``"coder"``, ``"admin"``).
        task_type: Task category (``"coding"``, ``"research"``, etc.).
            Empty string skips task-based models.
        cascade: Optional override list. If provided, returns it directly.

    Returns:
        Deduplicated list of model IDs, preserving order of first appearance.
    """
    if cascade is not None:
        return list(dict.fromkeys(cascade))

    combined: list[str] = list(_ROLE_MODEL_CASCADE.get(role, []))

    if task_type:
        try:
            from weebot.core.model_cascade_config import get_cascade_for_task

            task_models = get_cascade_for_task(task_type)
            for tm in task_models:
                if tm.id not in combined:
                    combined.append(tm.id)
        except Exception:
            pass  # graceful fallback — role-only is sufficient

    return combined


# ========================================================================
# ROLE_MODEL_CONFIG — consolidated from weebot.core.model_cascade_config
# ========================================================================
# This is the authoritative source for role→model mapping used by
# context switcher, role model selector, and harness profile resolver.
# Consumers should import from here, not from model_cascade_config.
# ========================================================================

ROLE_MODEL_CONFIG: dict[str, list[str]] = {
    # Z.ai GLM 5.2 :thinking (reasoning xhigh, 1M ctx) → DeepSeek Flash :thinking → Kimi K2.6 :thinking
    "planner": [
        "z-ai/glm-5.2:thinking",
        "deepseek/deepseek-v4-flash:thinking",
        "moonshotai/kimi-k2.6:thinking",
    ],
    # Cross-lab diversity: xAI Grok 4.3 :thinking (xAI lab ≠ Z.ai planner) → DeepSeek :thinking → Grok Build
    "critic": [
        "x-ai/grok-4.3:thinking",
        "moonshotai/kimi-k2.7-code",  # Kimi K2.7 Code — premium review
        "google/gemini-2.5-flash",  # Gemini 2.5 Flash — multimodal review
        "deepseek/deepseek-v4-flash:thinking",
        "x-ai/grok-build-0.1",
    ],
    # GLM 5.2 :thinking (primary, reasoning xhigh) -> DeepSeek Flash :thinking -> Kimi K2.6 :thinking
    "executor": [
        "z-ai/glm-5.2:thinking",
        "google/gemini-3.5-flash",  # Gemini 3.5 Flash — $1.50/1M, 1M ctx, agentic
        "deepseek/deepseek-v4-flash:thinking",
        "moonshotai/kimi-k2.6:thinking",
    ],
    # DeepSeek Flash :thinking (fast CoVe) → Grok 4.3 :thinking (factual) → Qwen Max
    "verifier": [
        "deepseek/deepseek-v4-flash:thinking",
        "x-ai/grok-4.3:thinking",
        "qwen/qwen3.8-max",
    ],
    # DeepSeek Flash (fast, cheap — no thinking needed for summarization)
    "summarizer": ["deepseek/deepseek-v4-flash", "minimax/minimax-m3", "moonshotai/kimi-k2.6"],
    # GPT-4.1 Nano (fast, no reasoning) → DeepSeek Flash :thinking (reasoning subagent) → Qwen Coder 30B
    "subagent": [
        "qwen/qwen3.7-flash",  # cheapest in catalog — $0.03/$0.13, 1M ctx
        "openai/gpt-4.1-nano",
        "poolside/laguna-xs-2.1",  # Laguna XS 2.1 — $0.10/1M coding agent
        "google/gemini-2.5-flash-lite",  # Gemini 2.5 Flash Lite — subagent
        "kwaipilot/kat-coder-air-v2.5",  # KAT-Coder-Air
        "minimax/minimax-m3",  # MiniMax M3 — budget 1M ctx
        "deepseek/deepseek-v4-flash:thinking",
        "qwen/qwen3-coder-30b-a3b-instruct",
    ],
    # Independent code review: xAI Grok 4.3 :thinking (xAI ≠ Z.ai executor) → DeepSeek :thinking → Grok Build
    "reviewer": [
        "x-ai/grok-4.3:thinking",
        "moonshotai/kimi-k2.7-code",  # Kimi K2.7 Code — premium review
        "google/gemini-2.5-flash",  # Gemini 2.5 Flash — multimodal review
        "deepseek/deepseek-v4-flash:thinking",
        "x-ai/grok-build-0.1",
    ],
    # Kimi K2.6 :thinking (broad knowledge, CoT) → GLM 5.2 :thinking → DeepSeek Flash :thinking
    "dreamer": [
        "moonshotai/kimi-k2.6:thinking",
        "z-ai/glm-5.2:thinking",
        "deepseek/deepseek-v4-flash:thinking",
    ],
}
