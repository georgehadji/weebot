"""Centralized LLM model name references.

9 allowed models — all explicit provider-qualified IDs.
``openrouter/auto`` is FORBIDDEN.

Cascade (4-tier) — verified against OpenRouter API 2026-06-07:
  Tier 1: NVIDIA Nemotron 3 Ultra — FREE, 1M ctx, reasoning, tools, 55B active/550B MoE
  Tier 2: MiniMax M3 — paid, 1M ctx, multimodal, thinking toggle
  Tier 3: Grok Build 0.1 — fast coding, agentic SWE
  Tier 4: Qwen 3.7 Max — flagship coding, 1M ctx

Task-specific:
  CODING:        Qwen 3.7 Max + Grok Build 0.1
  FILE_OPS:      MiniMax M3 (1M ctx, multimodal)
  RESEARCH:      Nemotron 3 Ultra (free, reasoning) — structured output
  REVIEW:        Grok 4.3 — reasoning, high factual accuracy
  PLANNING:      Nemotron 3 Ultra (free, reasoning) — structured planning
  SECURITY:      Grok 4.3 + DeepSeek V4 Pro — reasoning, factual accuracy
  SUMMARIZATION: MiniMax M3 (fast, 1M ctx)
  GENERAL:       Nemotron 3 Ultra (free, reasoning)
"""
from __future__ import annotations

# ========================================================================
# Executor Cascade (4-tier)
# ========================================================================
MODEL_CASCADE_TIER1: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
"""Tier 1: NVIDIA Nemotron 3 Ultra — FREE, 1M context, reasoning, tool support.
55B active parameters out of 550B total (MoE). Hybrid Transformer-Mamba architecture.
Verified on OpenRouter API 2026-06-07."""

MODEL_BUDGET: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
"""Budget/free model for non-critical operations (compression, curation, defaults)."""

MODEL_CASCADE_TIER2: str = "minimax/minimax-m3"
"""Tier 2: MiniMax M3 — FREE, 1M context, multimodal, thinking toggle."""

MODEL_CASCADE_TIER3: str = "x-ai/grok-build-0.1"
"""Tier 3: Grok Build 0.1 — fast coding model for agentic SWE workflows."""

MODEL_CASCADE_TIER4: str = "qwen/qwen3.7-max"
"""Tier 4: Qwen 3.7 Max — flagship agent-centric, coding strength, 1M context."""

# ========================================================================
# Task-specific
# ========================================================================
MODEL_PLANNER: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
"""Planning: Nemotron 3 Ultra — FREE, reasoning, structured planning."""

MODEL_CODE_REVIEW: str = "x-ai/grok-4.3"
"""Code review: Grok 4.3 — reasoning model, high factual accuracy, 1M context."""

MODEL_SUMMARIZE: str = "minimax/minimax-m3"
"""Summary: MiniMax M3 — fast, 1M context, multimodal."""

# ========================================================================
# Per-Agent (Role) Model Selection
# ========================================================================
MODEL_ROLE_RESEARCHER: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
"""Researcher: Nemotron 3 Ultra (free, reasoning) — structured output, broad knowledge, source synthesis."""

MODEL_ROLE_ANALYST: str = "deepseek/deepseek-v4-pro"
"""Analyst: DeepSeek V4 Pro — strongest math/reasoning, complex data analysis."""

MODEL_ROLE_CODER: str = "qwen/qwen3.7-max"
"""Coder: Qwen 3.7 Max — flagship coding, 1M context for large codebases."""

MODEL_ROLE_REVIEWER: str = "x-ai/grok-4.3"
"""Reviewer: Grok 4.3 — highest factual accuracy, reasoning, security audit."""

MODEL_ROLE_ADMIN: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
"""Admin: Nemotron 3 Ultra (free, reasoning) — orchestrates sub-agents, decomposes complex tasks."""

MODEL_ROLE_AUTOMATION: str = "z-ai/glm-5.1"
"""Automation: GLM-5.1 — best instruction following, safety-aware, reliable execution."""

MODEL_ROLE_DOCUMENTATION: str = "minimax/minimax-m3"
"""Documentation: MiniMax M3 — fast, 1M context, cheap, good for writing/formatting."""

# ── Role → Model cascade lookup (primary + 2 fallbacks) ────────────

_ROLE_MODEL_CASCADE: dict[str, list[str]] = {
    "researcher": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",  # primary: Nemotron 3 Ultra — free, reasoning
        "minimax/minimax-m3",                       # fallback 1: MiniMax M3 — 1M ctx, multimodal
        "qwen/qwen3.7-max",                         # fallback 2: Qwen Max — strong comprehension
    ],
    "analyst": [
        "deepseek/deepseek-v4-pro",                  # primary: DeepSeek V4 — best math/reasoning
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # fallback 1: Nemotron 3 Ultra — free, reasoning
        "x-ai/grok-4.3",                            # fallback 2: Grok 4.3 — factual accuracy
    ],
    "coder": [
        "qwen/qwen3.7-max",                          # primary: Qwen 3.7 Max — flagship coding
        "x-ai/grok-build-0.1",                       # fallback 1: Grok Build — fast agentic SWE
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # fallback 2: Nemotron 3 Ultra — free
    ],
    "reviewer": [
        "x-ai/grok-4.3",                             # primary: Grok 4.3 — factual accuracy
        "deepseek/deepseek-v4-pro",                  # fallback 1: DeepSeek V4 — reasoning
        "z-ai/glm-5.1",                              # fallback 2: GLM-5.1 — instruction following
    ],
    "admin": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # primary: Nemotron 3 Ultra — free, reasoning
        "qwen/qwen3.7-max",                          # fallback 1: Qwen Max — broad capability
        "minimax/minimax-m3",                        # fallback 2: MiniMax M3
    ],
    "automation": [
        "z-ai/glm-5.1",                              # primary: GLM-5.1 — instruction following
        "minimax/minimax-m3",                        # fallback 1: MiniMax M3 — reliable
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # fallback 2: Nemotron 3 Ultra — free
    ],
    "documentation": [
        "minimax/minimax-m3",                        # primary: MiniMax M3 — fast, cheap, 1M ctx
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # fallback 1: Nemotron 3 Ultra — free
        "z-ai/glm-5.1",                              # fallback 2: GLM-5.1 — structured output
    ],
    "product_manager": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "minimax/minimax-m3",
        "z-ai/glm-5.1",
    ],
    "planner": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",   # primary: Nemotron 3 Ultra — free, reasoning
        "minimax/minimax-m3",                        # fallback 1: MiniMax M3 — capable
        "x-ai/grok-build-0.1",                       # fallback 2: Grok Build — agentic
    ],
    "planner_sub": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "minimax/minimax-m3",
        "x-ai/grok-build-0.1",
    ],
    "designer": [
        "minimax/minimax-m3",                        # primary: fast, cheap
        "nvidia/nemotron-3-ultra-550b-a55b:free",
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
    return [
        MODEL_CASCADE_TIER1,
        MODEL_CASCADE_TIER2,
        MODEL_CASCADE_TIER3,
    ]

# ========================================================================
# DI container + factory defaults
# ========================================================================
MODEL_DI_DEFAULT: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
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
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "minimax/minimax-m3",
    "x-ai/grok-build-0.1",
    "qwen/qwen3.7-max",
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
    ]


# ========================================================================
# Image Generation Cascade — use-case → primary → fallback → free → SVG
# ========================================================================

IMAGE_CASCADE: dict[str, list[str]] = {
    # ── Website hero banners — photorealistic, high impact ──────────
    "hero": [
        "black-forest-labs/flux.2-pro",         # primary: photorealistic
        "x-ai/grok-imagine-image-quality",       # fallback: also photorealistic
        "sourceful/riverflow-v2.5-pro:free",     # free: good general quality
    ],

    # ── Logos, brand assets, icons — vector output preferred ────────
    "logo": [
        "recraft/recraft-v4.1-pro-vector",       # primary: professional SVG
        "recraft/recraft-v4.1-pro",               # fallback: raster if vector fails
        "sourceful/riverflow-v2.5-pro:free",     # free: decent logos
    ],

    # ── Small icons, favicons, UI elements ──────────────────────────
    "icon": [
        "recraft/recraft-v4.1-pro-vector",       # primary: clean vector
        "black-forest-labs/flux.2-klein-4b",     # fallback: cheap, fast
        "sourceful/riverflow-v2.5-fast:free",    # free: fast
    ],

    # ── Photorealistic — products, people, places ───────────────────
    "photo": [
        "black-forest-labs/flux.2-max",           # primary: max quality
        "black-forest-labs/flux.2-pro",           # fallback: still excellent
        "x-ai/grok-imagine-image-quality",        # fallback 2: photorealism focus
        "sourceful/riverflow-v2.5-pro:free",     # free
    ],

    # ── Diagrams, charts, UI mockups, technical illustrations ───────
    "diagram": [
        "google/gemini-2.5-flash-image",          # primary: specialized for this
        "recraft/recraft-v4.1-pro-vector",        # fallback: vector output
        "google/gemini-3.1-flash-image-preview",  # free: experimental Gemini
    ],

    # ── Social media, thumbnails — fast, cheap, decent ──────────────
    "social": [
        "sourceful/riverflow-v2.5-fast:free",     # primary: FREE + fast
        "black-forest-labs/flux.2-flex",           # fallback: batch-optimized
        "black-forest-labs/flux.2-klein-4b",      # fallback 2: cheapest paid
    ],

    # ── Text-heavy images — signs, banners with text ────────────────
    "text": [
        "bytedance-seed/seedream-4.5",             # primary: best text rendering
        "recraft/recraft-v4.1-pro-vector",         # fallback: vector text
        "sourceful/riverflow-v2.5-pro:free",      # free
    ],

    # ── Branded / enterprise — safety, consistency ──────────────────
    "brand": [
        "microsoft/mai-image-2.5",                 # primary: enterprise safety
        "recraft/recraft-v4.1-pro",                # fallback: consistent output
        "black-forest-labs/flux.2-pro",            # fallback 2: quality
    ],

    # ── General / catch-all ────────────────────────────────────────
    "general": [
        "sourceful/riverflow-v2.5-pro:free",      # primary: FREE, good
        "black-forest-labs/flux.2-pro",            # fallback: quality
        "google/gemini-2.5-flash-image",           # fallback 2: versatile
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
# Mixture-of-Agents
# ========================================================================
MODEL_MOA_REFERENCE: list[str] = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
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

    Verified against OpenRouter API 2026-06-07.
    ``nvidia/nemotron-3-ultra-550b-a55b:free`` is the recommended default.
    """
    return [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3.5-content-safety:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "qwen/qwen3-coder:free",
        "qwen/qwen3.6-plus:free",
        "google/gemini-2.0-flash-exp:free",
        "minimax/minimax-m3",
    ]
