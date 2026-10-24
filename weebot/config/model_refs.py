"""Which model serves which role, task and tier: ids only.

This module owns routing. It does not own model facts: price, context window,
modalities and supported parameters come from the generated OpenRouter catalog
(``weebot/config/model_catalog.py``, read through
``weebot.config.model_registry.get_model_config``). Do not quote a token price
or a context size here; it is a second copy that drifts (W6.1).

``openrouter/auto`` is FORBIDDEN. Every text id below must exist in the catalog
(``tests/unit/test_routed_models_exist.py``).

Choice, 2026-10-23: value for money per role, scored on the Artificial Analysis
Intelligence Index (v4.3.2, snapshot 2026-10-17..23) and its per-role component
(agentic automation, terminal coding, long-context reasoning, factuality,
writing) against measured cost per task. Ids are plain (no ``:thinking``):
that suffix forces ``reasoning_effort="max"`` in OpenAIAdapter, the most
expensive setting, on every call. Fallbacks come from other providers, so one
provider outage does not take a role down.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ========================================================================
# Executor cascade tiers
# ========================================================================
MODEL_CASCADE_TIER1: str = "deepseek/deepseek-v4.1-flash-1017"  # user pick, 2026-10-23
"""Tier 1, the executor workhorse: best agentic-automation score per dollar.
DeepSeek-direct first when DEEPSEEK_API_KEY is set, OpenRouter fallback."""

MODEL_CASCADE_TIER2: str = "minimax/minimax-m3.1-flash"
"""Tier 2, budget fallback from another provider; strong agentic automation."""

MODEL_CASCADE_TIER3: str = "xiaomi/mimo-v2.6-pro"
"""Tier 3, standard: near-frontier long-context reasoning at a mid price."""

MODEL_CASCADE_TIER4: str = "openai/gpt-6.1-sol"
"""Tier 4, premium: frontier reasoning at a fraction of the top models' cost."""

MODEL_BUDGET: str = "openai/gpt-6-luna"
"""Budget model for non-critical calls (compression, curation, judging):
cheapest measured cost per task, strict JSON-schema output."""

MODEL_VISION_PRIMARY: str = "openai/gpt-5.6-luna"
"""Vision: image input plus tool use at a budget price."""

# ========================================================================
# Verbalized Sampling
# ========================================================================
MODEL_VS_CAPABLE: str = MODEL_CASCADE_TIER4
"""VS-capable model: the premium tier. Paper: larger models benefit more."""


def get_vs_model() -> str:
    """Return the single source of truth for the VS-capable model."""
    return MODEL_VS_CAPABLE


# ========================================================================
# Web search — Perplexity Sonar (via OpenRouter)
# ========================================================================
MODEL_SEARCH_PERPLEXITY_SONAR: str = "perplexity/sonar"
"""Web search: search-grounded answers with citations and search_results."""

# ========================================================================
# Role -> model cascade (primary, then fallbacks)
# ========================================================================
# The one role table. It used to be two (`_ROLE_MODEL_CASCADE` for the executor
# cascade, `ROLE_MODEL_CONFIG` for DI's per-role LLMs, the context switcher,
# the role model selector and the harness profile resolver), and the two gave
# `planner`, `executor` and `reviewer` different models.
_DEEPSEEK = MODEL_CASCADE_TIER1
_MINIMAX = MODEL_CASCADE_TIER2
_MIMO_PRO = MODEL_CASCADE_TIER3
_SOL = MODEL_CASCADE_TIER4
_LUNA = MODEL_BUDGET
# Replaced Gemini 4 Argon (AA 53, $1.99/task, 60 s) on 2026-10-23: AA 55,
# $2.11/task, 35 s end to end, tool calls verified live through OpenRouter.
_KIMI = "moonshotai/kimi-k3.1-pro"
_SONNET = "anthropic/claude-sonnet-5.5"
_OPUS = "anthropic/claude-opus-5.5"
_HAIKU = "anthropic/claude-haiku-5.5"

# User rule (2026-10-23): of Claude models, only Opus, Sonnet and Haiku 5.5;
# never Fable. Paths that pick from the live list (the cascade's rescue, the
# ACR pool) filter through this. Pinned by tests/unit/test_claude_model_rule.py.
_ALLOWED_CLAUDE = re.compile(r"^(anthropic/)?claude-(opus|sonnet|haiku)-5[.-]5(:[a-z]+)?$")


def claude_model_allowed(model_id: str) -> bool:
    """False only for a Claude model outside the user's allowed set."""
    return "claude" not in model_id.lower() or bool(_ALLOWED_CLAUDE.match(model_id.lower()))
_MIMO_FLASH = "xiaomi/mimo-v2.6-flash"
_GLM = "z-ai/glm-5.3"
_GLM_FLASH = "z-ai/glm-5.3-flash"
_QWEN_FLASH = "qwen/qwen3.8-flash"

ROLE_MODEL_CONFIG: dict[str, list[str]] = {
    # Reasoning-heavy, one call per plan: quality per dollar at the top end.
    # Haiku 5.5 first for planner and researcher: on the 2026-10-23 billed
    # hard-task eval it tied the previous primaries at 3x to 10x lower cost
    # (tasks/remaining_fix_plan.md); the previous primary is fallback 1. The
    # coder stays on Sonnet: in multi-step coding runs Haiku went 2/3 (it
    # rewrote a task's input) against Sonnet's 3/3.
    "planner": [_HAIKU, _SOL, _KIMI, _MIMO_PRO],
    "planner_sub": [_MIMO_PRO, _DEEPSEEK, _SOL],
    # Highest volume: the agentic tool loop.
    "executor": [_DEEPSEEK, _MIMO_PRO, _MINIMAX, _GLM_FLASH],
    # Sol first: billed 2026-10-23 coding eval, 5 tasks pinned per model, Sol
    # 5/5 in 333 s vs Sonnet 4/5 in 1141 s, at ~1/3 the AA cost per task
    # (tasks/audits/model_routing_2026_10_23.md). Sonnet is fallback 1.
    "coder": [_SOL, _SONNET, _GLM, _DEEPSEEK],
    # Haiku 5.5 tied Sol 6/6 on the billed subtle-bug eval at ~1/12 the cost.
    # Sol (another lab than the Anthropic coder) is fallback 1.
    "reviewer": [_HAIKU, _SOL, _KIMI, _OPUS],
    "critic": [_SOL, _KIMI, _OPUS],
    "verifier": [_DEEPSEEK, _MIMO_FLASH, _HAIKU],
    "researcher": [_HAIKU, _MIMO_PRO, _SOL, _DEEPSEEK],
    "analyst": [_SOL, _MIMO_PRO, _KIMI],
    "dreamer": [_MIMO_PRO, _DEEPSEEK, _SOL],
    "product_manager": [_MIMO_PRO, _SOL, _HAIKU],
    "designer": [_MIMO_PRO, _SONNET, _DEEPSEEK],
    "documentation": [_HAIKU, _MIMO_FLASH, _QWEN_FLASH],
    "summarizer": [_HAIKU, _MIMO_FLASH, _QWEN_FLASH],
    # DeepSeek first (AA 45, $0.26/task, 14 s) over MiniMax (43, $0.22, 30 s):
    # tasks/audits/model_routing_2026_10_23.md.
    "automation": [_DEEPSEEK, _MINIMAX, _MIMO_FLASH],
    "admin": [_DEEPSEEK, _MINIMAX, _MIMO_PRO],
    "subagent": [_LUNA, _MIMO_FLASH, _HAIKU, _GLM_FLASH],
    "vision": [MODEL_VISION_PRIMARY, _HAIKU, "google/gemini-3.8-flash", _MIMO_FLASH],
}

_DEFAULT_ROLE_CASCADE: list[str] = [_DEEPSEEK, _MIMO_PRO, _SOL]

# Priced at the top: the ACR bandit explores these less.
PREMIUM_MODELS: frozenset[str] = frozenset({_SOL, _KIMI, _SONNET, _OPUS})


def get_model_cascade_for_role(role: str | None) -> list[str]:
    """Return the model cascade (primary, then fallbacks) for an agent role.

    ``None`` or an unknown role gets the default cascade: the three tiers above
    the budget one.
    """
    cascade = (
        list(ROLE_MODEL_CONFIG[role])
        if role and role in ROLE_MODEL_CONFIG
        else list(_DEFAULT_ROLE_CASCADE)
    )
    local = _local_model_for_role(role)
    cascade = [local, *cascade] if local else cascade
    # The user's pick from the UI goes first; everything else stays as its fallback.
    from weebot.config.role_overrides import get_overrides

    chosen = get_overrides().get(role or "")
    return [chosen, *(m for m in cascade if m != chosen)] if chosen else cascade


def _local_model_for_role(role: str | None) -> str | None:
    """``ollama/<tag>`` when Ollama is on and *role* is listed in OLLAMA_ROLES, else None.

    The Ollama model goes first and the normal cascade stays behind it, so a stopped server,
    a spent cloud quota or a slow answer falls through to the models used before.
    """
    if not role:
        return None
    from weebot.config.local_models import local_model_id, role_models

    tag = role_models().get(role)
    return local_model_id(tag) if tag else None


# Sub-agent model per AgentTier value ("budget", "standard", "premium"), for a
# spec that names no model. AgentTier is a str enum, so its members key this.
SUBAGENT_TIER_MODEL: dict[str, str] = {
    "budget": MODEL_CASCADE_TIER2,
    "standard": MODEL_CASCADE_TIER3,
    "premium": MODEL_CASCADE_TIER4,
}

# ========================================================================
# Task -> model cascade (the context switcher)
# ========================================================================
# Ids only; the per-task price list that used to sit beside these in
# core/model_cascade_config.py was a third copy of catalog prices.
TASK_MODEL_CASCADE: dict[str, list[str]] = {
    "coding": [_DEEPSEEK, _MINIMAX, _SONNET],
    # Past the long-context threshold: the best long-context reasoning score
    # per dollar, with a 1M window.
    "long_context": [_MIMO_PRO, _DEEPSEEK],
}

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = MODEL_CASCADE_TIER1
MODEL_DI_SKILLOPT: str = MODEL_CASCADE_TIER4

# Per-provider defaults: the model a provider's adapter asks for when the caller
# names none. Each must be a model THAT provider's own API serves, as its bare
# native ID -- the factory strips any `vendor/` prefix, and AnthropicAdapter and
# BrowserTool's ChatOpenAI fallback send the value as-is to api.anthropic.com /
# api.openai.com. The OPENAI and ANTHROPIC values had drifted to
# "moonshotai/kimi-k2.6" and "qwen/qwen3.8-max" in two unrelated cascade
# reorders, so both defaults requested a model their endpoint does not serve.
# Pinned by tests/unit/test_provider_defaults.py.
MODEL_FACTORY_OPENAI: str = "gpt-5.4-mini"
MODEL_FACTORY_ANTHROPIC: str = "claude-sonnet-5.5"
MODEL_FACTORY_DEEPSEEK: str = MODEL_CASCADE_TIER1
MODEL_FACTORY_OPENROUTER: str = MODEL_CASCADE_TIER1

# OpenAIAdapter's own default when constructed directly. "OPENAI" here names the
# OpenAI-compatible protocol, not the vendor: a `vendor/id` default makes the
# adapter pick OpenRouter's base URL, which serves this ID.
MODEL_DEFAULT_OPENAI: str = MODEL_CASCADE_TIER1

# ========================================================================
# Fallback chain
# ========================================================================
# Ten models, six labs, cheapest first after the workhorse.
MODEL_FALLBACK_OPENROUTER_CHAIN: list[str] = [
    _DEEPSEEK,
    _MINIMAX,
    _MIMO_FLASH,
    _HAIKU,
    _LUNA,
    _QWEN_FLASH,
    _MIMO_PRO,
    _GLM,
    _SOL,
    "deepseek/deepseek-v4-flash",  # previous workhorse, cheapest last resort
]
MODEL_FALLBACK_NON_OPENROUTER: str = MODEL_BUDGET

# ========================================================================
# CQRS / deprecated
# ========================================================================
MODEL_COMMAND_DEFAULT: str = MODEL_BUDGET
MODEL_DEPRECATED_TOOL_AGENT: str = MODEL_BUDGET

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
"""Ideogram 3.0 Turbo — best text rendering, logos, branding, typography ($0.03/img).
Direct Ideogram API only (IDEOGRAM_API_KEY): OpenRouter lists no Ideogram models
as of 2026-09, so ImageGenTool skips ideogram/* in its cascade when that key is
unset rather than spending an attempt on a guaranteed 404."""

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

MODEL_VIDEO_VEO_FAST: str = "google/veo-3.1-fast"
"""Google Veo 3.1 Fast — from $0.10/video. Fast inference."""

MODEL_VIDEO_VEO_LITE: str = "google/veo-3.1-lite"
"""Google Veo 3.1 Lite — from $0.05/video. Budget option."""

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

MODEL_VIDEO_SEEDANCE_15: str = "bytedance/seedance-1-5-pro"
"""ByteDance Seedance 1.5 Pro — from $0.023/video. Cheapest option."""

MODEL_VIDEO_SORA_2: str = "openai/sora-2-pro"
"""OpenAI Sora 2 Pro — from $0.30/video. Premium quality."""

MODEL_VIDEO_VEO_31: str = "google/veo-3.1"
"""Google Veo 3.1 — from $0.40/video. Highest quality."""


def get_video_models() -> list[str]:
    """Return the canonical list of video generation model IDs."""
    return [
        "x-ai/grok-imagine-video",
        "google/veo-3.1-fast",
        "google/veo-3.1-lite",
        "minimax/hailuo-2.3",
        "bytedance/seedance-2.0",
        "bytedance/seedance-2.0-fast",
        "alibaba/wan-2.7",
        "alibaba/wan-2.6",
        "bytedance/seedance-1-5-pro",
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
    ],
    # ── Cinematic / narrative — quality first ───────────────────
    "cinematic": [
        "openai/sora-2-pro",  # 1st: premium
        "google/veo-3.1",  # 2nd: highest quality Google
        "minimax/hailuo-2.3",  # 3rd: strong cinematic
    ],
    # ── Product demos / marketing ───────────────────────────────
    "product": [
        "alibaba/wan-2.7",  # 1st: good general
        "google/veo-3.1-fast",  # 3rd: fast
    ],
    # ── Brand / enterprise — safety, consistency ────────────────
    "brand": [
        "x-ai/grok-imagine-video-1.5",  # 1st: direct xAI — v1.5 with audio
        "x-ai/grok-imagine-video",  # 2nd: direct xAI — v1 fallback
        "google/veo-3.1",  # 3rd: professional
    ],
    # ── General / catch-all — free → cheap → best ──────────────
    "general": [
        "x-ai/grok-imagine-video-1.5",  # 1st: direct xAI — v1.5 with audio
        "x-ai/grok-imagine-video",  # 2nd: direct xAI — v1 fallback
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
# Reference models from four labs; the first is also the default aggregator.
MODEL_MOA_REFERENCE: list[str] = [_MIMO_PRO, _DEEPSEEK, _MINIMAX, _HAIKU]


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
    from weebot.config.constants import DEFAULT_HARNESS_VERSION

    return f"weebot/config/harness/{DEFAULT_HARNESS_VERSION}.yaml"


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
