"""Centralized LLM model name references.

9 allowed models — all explicit provider-qualified IDs.
``openrouter/auto`` is FORBIDDEN.

Cascade (2-tier direct API + 2-tier OpenRouter):
  Tier 1: Kimi K2.6 — via KIMI_API_KEY (direct), OpenRouter fallback
  Tier 2: DeepSeek V4 Flash — via DEEPSEEK_API_KEY (direct), OpenRouter fallback
  Tier 3: Grok Build 0.1 — fast coding, agentic SWE (OpenRouter)
  Tier 4: Qwen 3.7 Max — flagship coding, 1M ctx (OpenRouter)

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

MODEL_BUDGET: str = "x-ai/grok-build-0.1"
"""Budget model for non-critical operations (compression, curation, defaults).
Same as Tier 1 — fast coding model via direct XAI_API_KEY."""

MODEL_CASCADE_TIER2: str = "deepseek/deepseek-v4-flash"
"""Tier 2: DeepSeek V4 Flash — fast fallback.
Direct API via DEEPSEEK_API_KEY (preferred). OpenRouter fallback.
Native model ID: ``deepseek-v4-flash`` (stripped by DeepSeekAdapter)."""

MODEL_CASCADE_TIER3: str = "moonshotai/kimi-k2.6"
"""Tier 3: Kimi K2.6 — structured output, broad knowledge, 256K context."""

MODEL_CASCADE_TIER4: str = "qwen/qwen3.7-max"
"""Tier 4: Qwen 3.7 Max — flagship agent-centric, coding strength, 1M context."""

# ═══════════════════════════════════════════════════════════════════════
# Verbalized Sampling
# ═══════════════════════════════════════════════════════════════════════
MODEL_VS_CAPABLE: str = MODEL_CASCADE_TIER4
"""VS-capable model: same as Tier 4 (Qwen 3.7 Max). Paper: larger models benefit more."""

MODEL_VS_FALLBACK: str = "x-ai/grok-build-0.1"
"""VS fallback when Tier 4 unavailable."""


def get_vs_model() -> str:
    """Return the single source of truth for the VS-capable model."""
    return MODEL_VS_CAPABLE

# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "x-ai/grok-build-0.1"
"""Planning: Grok Build 0.1 — fast coding model for agentic planning via direct XAI_API_KEY."""

MODEL_CODE_REVIEW: str = "x-ai/grok-4.3"
"""Code review: Grok 4.3 — reasoning model, high factual accuracy, 1M context."""

MODEL_SUMMARIZE: str = "deepseek/deepseek-v4-flash"
"""Summary: DeepSeek V4 Flash — fast, cheap, good summarization via DEEPSEEK_API_KEY."""

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
        "moonshotai/kimi-k2.6",                   # primary: Kimi K2.6 — direct API, structured output
        "deepseek/deepseek-v4-flash",             # fallback 1: DeepSeek V4 Flash — fast
        "qwen/qwen3.7-max",                       # fallback 2: Qwen Max — strong comprehension
    ],
    "analyst": [
        "deepseek/deepseek-v4-flash",             # primary: DeepSeek V4 Flash — fast math/reasoning
        "moonshotai/kimi-k2.6",                   # fallback 1: Kimi K2.6
        "x-ai/grok-4.3",                          # fallback 2: Grok 4.3 — factual accuracy
    ],
    "coder": [
        "x-ai/grok-build-0.1",                    # primary: Grok Build — fast agentic SWE
        "deepseek/deepseek-v4-flash",             # fallback 1: DeepSeek V4 Flash — fast coding
        "moonshotai/kimi-k2.6",                   # fallback 2: Kimi K2.6 — structured output
    ],
    "executor": [
        "z-ai/glm-5.2",                           # primary: GLM 5.2 — 1M ctx, long-horizon, strong coding
        "deepseek/deepseek-v4-flash",             # fallback 1: DeepSeek V4 Flash — fast
        "moonshotai/kimi-k2.6",                   # fallback 2: Kimi K2.6 — structured output
    ],
    "reviewer": [
        "x-ai/grok-4.3",                          # primary: Grok 4.3 — factual accuracy
        "deepseek/deepseek-v4-flash",             # fallback 1: DeepSeek V4 Flash — reasoning
        "moonshotai/kimi-k2.6",                   # fallback 2: Kimi K2.6
    ],
    "admin": [
        "x-ai/grok-build-0.1",                    # primary: Grok Build — fast agentic SWE
        "x-ai/grok-4.3",                          # fallback 1: Grok 4.3 — factual accuracy
        "moonshotai/kimi-k2.6",                   # fallback 2: Kimi K2.6 — structured output
    ],
    "automation": [
        "x-ai/grok-build-0.1",                    # primary: Grok Build — fast agentic SWE
        "deepseek/deepseek-v4-flash",             # fallback 1: DeepSeek V4 Flash — instruction following
        "moonshotai/kimi-k2.6",                   # fallback 2: Kimi K2.6
    ],
    "documentation": [
        "deepseek/deepseek-v4-flash",             # primary: DeepSeek V4 Flash — fast, cheap
        "moonshotai/kimi-k2.6",                   # fallback 1: Kimi K2.6
        "minimax/minimax-m3",                     # fallback 2: MiniMax M3
    ],
    "product_manager": [
        "moonshotai/kimi-k2.6",
        "deepseek/deepseek-v4-flash",
        "minimax/minimax-m3",
    ],
    "planner": [
        "moonshotai/kimi-k2.6",                   # primary: Kimi K2.6 — structured planning
        "deepseek/deepseek-v4-flash",             # fallback 1: DeepSeek V4 Flash
        "x-ai/grok-build-0.1",                    # fallback 2: Grok Build — agentic
    ],
    "planner_sub": [
        "moonshotai/kimi-k2.6",
        "deepseek/deepseek-v4-flash",
        "x-ai/grok-build-0.1",
    ],
    "designer": [
        "deepseek/deepseek-v4-flash",             # primary: fast, cheap
        "moonshotai/kimi-k2.6",
        "sourceful/riverflow-v2.5-pro:free",
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
    return [
        "x-ai/grok-build-0.1",
        "x-ai/grok-4.3",
        MODEL_CASCADE_TIER1,
    ]

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "x-ai/grok-build-0.1"
MODEL_DI_SKILLOPT: str = "x-ai/grok-4.3"

MODEL_FACTORY_OPENAI: str = "moonshotai/kimi-k2.6"
MODEL_FACTORY_ANTHROPIC: str = "qwen/qwen3.7-max"
MODEL_FACTORY_DEEPSEEK: str = "deepseek/deepseek-v4-flash"
MODEL_FACTORY_OPENROUTER: str = "moonshotai/kimi-k2.6"

MODEL_DEFAULT_OPENAI: str = "moonshotai/kimi-k2.6"
MODEL_DEFAULT_ANTHROPIC: str = "qwen/qwen3.7-max"
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
    "qwen/qwen3.7-max",
    "x-ai/grok-4.3",
    "minimax/minimax-m3",
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
# Image Generation Models (text → image via OpenRouter)
# ========================================================================
MODEL_IMAGE_FREE: str = "sourceful/riverflow-v2.5-pro:free"
"""Default free image generation: Sourceful Riverflow V2.5 Pro — FREE, high quality."""

MODEL_IMAGE_FAST: str = "sourceful/riverflow-v2.5-fast:free"
"""Fast free image generation: Sourceful Riverflow V2.5 Fast — FREE, 2-3x faster."""

MODEL_IMAGE_VECTOR: str = "recraft/recraft-v4.1-pro-vector"
"""Professional vector/SVG generation: Recraft V4.1 Pro Vector — logos, icons, brand assets."""

MODEL_IMAGE_PHOTOREALISTIC: str = "black-forest-labs/flux.2-pro"
"""Photorealistic image generation: Flux.2 Pro — highest quality photorealism."""

MODEL_IMAGE_WEBSITE: str = "google/gemini-2.5-flash-image"
"""Website image generation: Gemini 2.5 Flash Image — diagrams, UI mockups, illustrations."""


MODEL_IMAGE_IDEOGRAM: str = "ideogram/ideogram-v3-turbo"
"""Ideogram 3.0 Turbo — best text rendering, logos, branding, typography ($0.03/img)."""

def get_image_models() -> list[str]:
    """Return the canonical list of image generation model IDs."""
    return [
        "sourceful/riverflow-v2.5-pro:free",
        "sourceful/riverflow-v2.5-fast:free",
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
    ]


# ========================================================================
# Image Generation Cascade — use-case → primary → fallback → free → SVG
# ========================================================================

IMAGE_CASCADE: dict[str, list[str]] = {
    # ── Website hero banners — photorealistic, high impact ──────────
    "hero": [
        "sourceful/riverflow-v2.5-pro:free",     # 1st: FREE — good general quality
        "x-ai/grok-imagine-image-quality",       # 2nd: cheap (~$0.05/img) — direct xAI
        "black-forest-labs/flux.2-pro",           # 3rd: paid — photorealistic
    ],

    # ── Logos, brand assets, icons — vector output preferred ────────
    "logo": [
        "ideogram/ideogram-v3-turbo",             # 1st: paid — best text/logo rendering
        "recraft/recraft-v4.1-pro-vector",       # 2nd: paid — professional SVG
        "recraft/recraft-v4.1-pro",               # 3rd: paid — raster fallback
    ],

    # ── Small icons, favicons, UI elements ──────────────────────────
    "icon": [
        "sourceful/riverflow-v2.5-fast:free",    # 1st: FREE — fast
        "black-forest-labs/flux.2-klein-4b",     # 2nd: cheap — fastest paid
        "recraft/recraft-v4.1-pro-vector",       # 3rd: paid — clean vector
    ],

    # ── Photorealistic — products, people, places ───────────────────
    "photo": [
        "sourceful/riverflow-v2.5-pro:free",     # 1st: FREE
        "x-ai/grok-imagine-image-quality",       # 2nd: cheap (~$0.05/img) — direct xAI
        "black-forest-labs/flux.2-pro",           # 3rd: paid — excellent quality
        "black-forest-labs/flux.2-max",           # 4th: paid — max quality
    ],

    # ── Diagrams, charts, UI mockups, technical illustrations ───────
    "diagram": [
        "google/gemini-3.1-flash-image-preview", # 1st: FREE — experimental Gemini
        "google/gemini-2.5-flash-image",          # 2nd: cheap — specialized
        "recraft/recraft-v4.1-pro-vector",        # 3rd: paid — vector output
    ],

    # ── Social media, thumbnails — fast, cheap, decent ──────────────
    "social": [
        "sourceful/riverflow-v2.5-fast:free",     # 1st: FREE + fast
        "black-forest-labs/flux.2-klein-4b",      # 2nd: cheapest paid
        "black-forest-labs/flux.2-flex",           # 3rd: batch-optimized
    ],

    # ── Text-heavy images — signs, banners with text ────────────────
    "text": [
        "ideogram/ideogram-v3-turbo",             # 1st: paid — industry-leading text rendering
        "recraft/recraft-v4.1-pro-vector",        # 2nd: paid — vector text
        "bytedance-seed/seedream-4.5",             # 3rd: paid — best text rendering
    ],

    # ── Branded / enterprise — safety, consistency ──────────────────
    "brand": [
        "ideogram/ideogram-v3-turbo",             # 1st: paid — brand-accurate text + logos
        "recraft/recraft-v4.1-pro",               # 2nd: paid — consistent output
        "microsoft/mai-image-2.5",                # 3rd: paid — enterprise safety
    ],

    # ── General / catch-all ────────────────────────────────────────
    "general": [
        "sourceful/riverflow-v2.5-pro:free",      # 1st: FREE — high quality
        "x-ai/grok-imagine-image-quality",        # 2nd: cheap (~$0.05/img) — direct xAI
        "black-forest-labs/flux.2-pro",            # 3rd: paid — photorealistic
    ],
}


def get_image_model_for(use_case: str, tier: int = 0, free_only: bool = False) -> str:
    """Return the best image model for *use_case* at the given cascade tier.

    Args:
        use_case: One of 'hero', 'logo', 'icon', 'photo', 'diagram',
                  'social', 'text', 'brand', 'general'.
        tier: 0 = primary, 1 = first fallback, 2 = second fallback, etc.
        free_only: If True, skip paid models and return the first free one.

    Returns:
        Model ID string, or the SVG template fallback marker 'svg:hero',
        'svg:logo', etc. when no API model is appropriate.

    Raises:
        KeyError: If *use_case* is not recognized.
    """
    cascade = IMAGE_CASCADE.get(use_case, IMAGE_CASCADE["general"])
    if free_only:
        for m in cascade:
            if ":free" in m:
                return m
        return "svg:" + use_case  # ultimate fallback: template SVG
    if tier < len(cascade):
        return cascade[tier]
    return cascade[-1]  # clamp to last available


def describe_image_cascade(use_case: str) -> str:
    """Return a human-readable description of the cascade for *use_case*."""
    cascade = IMAGE_CASCADE.get(use_case, IMAGE_CASCADE["general"])
    labels = ["Primary", "Fallback 1", "Fallback 2", "Fallback 3", "Fallback 4"]
    lines = [f"  {labels[i] if i < len(labels) else f'Tier {i}'}: {m}"
             for i, m in enumerate(cascade)]
    lines.append(f"  Ultimate: SVG template ({use_case})")
    return "\n".join(lines)


# ========================================================================
# Video Generation Models (text → video via OpenRouter)
# ========================================================================

MODEL_VIDEO_XAI: str = "x-ai/grok-imagine-video"
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
        "bytedance/seedance-2.0-fast",           # 1st: fast + cheap
        "bytedance/seedance-2.0",                 # 2nd: better quality
        "kling/video-v3-standard",                # 3rd: standard quality
    ],
    # ── Cinematic / narrative — quality first ───────────────────
    "cinematic": [
        "openai/sora-2-pro",                      # 1st: premium
        "google/veo-3.1",                         # 2nd: highest quality Google
        "minimax/hailuo-2.3",                     # 3rd: strong cinematic
        "kling/video-v3-pro",                     # 4th: pro quality
    ],
    # ── Product demos / marketing ───────────────────────────────
    "product": [
        "alibaba/wan-2.7",                        # 1st: good general
        "kling/video-v3-pro",                     # 2nd: pro quality
        "google/veo-3.1-fast",                    # 3rd: fast
    ],
    # ── Brand / enterprise — safety, consistency ────────────────
    "brand": [
        "x-ai/grok-imagine-video",                # 1st: direct xAI
        "google/veo-3.1",                         # 2nd: professional
        "kling/video-o1-pro",                     # 3rd: reasoning-enhanced
    ],
    # ── General / catch-all — free → cheap → best ──────────────
    "general": [
        "x-ai/grok-imagine-video",                # 1st: direct xAI
        "kling/video-v3-standard",                # 2nd: standard
        "alibaba/wan-2.6",                        # 3rd: budget
        "google/veo-3.1-lite",                    # 4th: lite
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
    "qwen/qwen3.7-max",
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

    Verified against OpenRouter API 2026-06-07.
    ``nvidia/nemotron-3-ultra-550b-a55b:free`` is the recommended default.
    ``nvidia/nemotron-3.5-content-safety:free`` excluded — too slow at inference.
    """
    return [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "qwen/qwen3-coder:free",
        "qwen/qwen3.6-plus:free",
        "google/gemini-2.0-flash-exp:free",
        "minimax/minimax-m3",
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

RERANK_MODEL_FREE: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
"""NVIDIA Nemotron Rerank VL 1B — free tier via OpenRouter.
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
        "research": RERANK_MODEL_PRO,      # multi-source synthesis — quality matters
        "skills": RERANK_MODEL_PRO,        # BM25 → semantic — quality matters
        "evaluation": RERANK_MODEL_PRO,    # staged evaluator — quality matters
        "search": RERANK_MODEL_FREE,       # web search — high-throughput, free tier
        "compressor": RERANK_MODEL_FREE,   # conversation compressor — high-throughput
        "memory": RERANK_MODEL_FREE,       # memory archivist — high-throughput
        "knowledge": RERANK_MODEL_FREE,    # knowledge graph FTS5 — high-throughput
    }
    return _rerank_map.get(use_case, RERANK_MODEL_FREE)


def get_models_for_role_and_task(
    role: str,
    task_type: str = "",
    cascade: list[str] | None = None,
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
    # Moonshot (primary) → NVIDIA frontier (deep plan) → DeepSeek (budget)
    "planner": [
        "moonshotai/kimi-k2.6:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "deepseek/deepseek-v4-flash",
    ],
    # Cross-lab diversity: OpenAI OSS → NousResearch → xAI (paid fallback)
    "critic": [
        "openai/gpt-oss-120b:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "x-ai/grok-build-0.1",
    ],
    # Qwen Coder (coding-specialist MoE) → Poolside (coding agent) → Kimi → DeepSeek
    "executor": [
        "qwen/qwen3-coder:free",
        "poolside/laguna-m.1:free",
        "moonshotai/kimi-k2.6:free",
        "deepseek/deepseek-v4-flash",
    ],
    # NVIDIA reasoning models purpose-built for sub-agent/verification roles
    "verifier": [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nex-agi/nex-n2-pro:free",
        "deepseek/deepseek-v4-flash",
    ],
    # Meta Llama (battle-tested) → Google Gemma → Kimi
    "summarizer": [
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemma-4-31b-it:free",
        "moonshotai/kimi-k2.6:free",
    ],
    # Fast, disposable: OpenAI OSS 20B → Poolside XS → GPT-4.1 Nano (budget)
    "subagent": [
        "openai/gpt-oss-20b:free",
        "poolside/laguna-xs.2:free",
        "openai/gpt-4.1-nano",
    ],
    # Independent code review: cross-lab from executor's Qwen Coder
    "reviewer": [
        "openai/gpt-oss-120b:free",
        "nousresearch/hermes-3-llama-3.1-405b:free",
        "x-ai/grok-build-0.1",
    ],
    # Idea synthesis: Kimi for multi-signal reasoning
    "dreamer": [
        "moonshotai/kimi-k2.6:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "deepseek/deepseek-v4-flash",
    ],
}
