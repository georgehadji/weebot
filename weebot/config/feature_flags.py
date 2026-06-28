"""Feature flags for weebot — gating experimental or high-risk capabilities.

Each flag defaults to OFF.  Flags should be toggled via environment variables
or a config file, never hardcoded to True in production.

HyperAgents Enhancement 7: METACOGNITIVE_IMPROVEMENT_ENABLED controls whether
the SelfImprover can edit its own prompt and allowlist (self-referential
improvement).  Default OFF — requires explicit opt-in.
"""
from __future__ import annotations

import os
from typing import Any, Callable


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean feature flag from an environment variable.

    Accepts '1', 'true', 'yes', 'on' (case-insensitive) as True.
    """
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


# ── HyperAgents Enhancement 7 ───────────────────────────────────────────────
# When True, the SelfImprover can modify its own prompt and configuration.
# This enables metacognitive self-improvement but carries operational risk:
# a bad self-modification could degrade the improvement pipeline itself.
# Always review meta-edits in MetaImprovementLog after enabling.
METACOGNITIVE_IMPROVEMENT_ENABLED: bool = _env_bool(
    "WEEBOT_METACOGNITIVE_IMPROVEMENT", default=False
)


# ── Deployment-time learning (Memento-Skills plan, Phases 1–5) ──────────────
# Each phase ships behind a default-OFF flag. Phase 0 (foundations) is always
# active but inert until a downstream phase is enabled.

# Phase 1 — distil a new skill from a completed task (quarantined on creation).
LIVE_SKILL_DISTILLATION_ENABLED: bool = _env_bool(
    "WEEBOT_LIVE_SKILL_DISTILLATION", default=False
)
# Phase 2 — on a retrieval miss, enqueue a gated skill-creation request.
SKILL_GAP_TRIGGER_ENABLED: bool = _env_bool(
    "WEEBOT_SKILL_GAP_TRIGGER", default=False
)
# Phase 3 — add a semantic (embedding) first stage to skill retrieval.
SEMANTIC_SKILL_RETRIEVAL_ENABLED: bool = _env_bool(
    "WEEBOT_SEMANTIC_SKILL_RETRIEVAL", default=False
)
# Phase 3b — replace keyword task router with embedding-based classification.
WEEBOT_SEMANTIC_TASK_ROUTER: bool = _env_bool(
    "WEEBOT_SEMANTIC_TASK_ROUTER", default=False
)
# Phase 4 — let the curator act (archive) and validate/dedup imports.
CURATION_ACTIONS_ENABLED: bool = _env_bool(
    "WEEBOT_CURATION_ACTIONS", default=False
)
# Phase 5 — attribute live failures to a skill and run online SkillOpt.
ONLINE_SKILLOPT_ENABLED: bool = _env_bool(
    "WEEBOT_ONLINE_SKILLOPT", default=False
)


# ── Product-Mode (product-led thinking pipeline) ──────────────────────────
# Master switch for the product thinking enhancements:
# Planner prompt augmentation, ProductGateState, outcome verification.
# Default OFF — enable via WEEBOT_PRODUCT_MODE=true
PRODUCT_MODE_ENABLED: bool = _env_bool(
    "WEEBOT_PRODUCT_MODE", default=False
)
# When True, emit ProductDecisionEvent on session completion for non-trivial
# tasks with ProductContext available.
PRODUCT_DECISION_LOG_ENABLED: bool = _env_bool(
    "WEEBOT_PRODUCT_DECISION_LOG", default=False
)


# ── Vision-in-the-loop (PicoAgents audit) ───────────────────────────────────
# When True, tool results carrying a screenshot (ToolResult.base64_image) are
# injected back into the conversation as an image message, so a vision-capable
# model can *see* the browser/desktop state instead of driving it blind off DOM
# text + OCR. Only the most recent screenshot is kept live (token control).
# Plan: tasks/specs/picoagents_vision_in_loop_spec.md
VISION_IN_LOOP_ENABLED: bool = _env_bool(
    "WEEBOT_VISION_IN_LOOP", default=True
)

# Phase 2 reflection: after screenshot injection, make a structured LLM call to produce
# PageObservation + NextActionPlan JSON. Adds one extra LLM round-trip per screenshot.
# Requires VISION_IN_LOOP_ENABLED=True and a vision-capable model.
# COST: with both flags on, each screenshot is sent twice — once in the reflection
# call here, and once in the buffer that the next main call reads — so expect ~2x
# image tokens plus the extra round-trip. Keep off unless reflection earns its cost.
# Plan: tasks/specs/picoagents_vision_in_loop_spec.md (Phase 2)
VISION_REFLECTION_ENABLED: bool = _env_bool(
    "WEEBOT_VISION_REFLECTION", default=True
)


def is_enabled(flag_name: str) -> bool:
    """Check if a feature flag is enabled by name."""
    return globals().get(flag_name, False)


def require(flag_name: str) -> None:
    """Raise RuntimeError if *flag_name* is not enabled."""
    if not is_enabled(flag_name):
        raise RuntimeError(
            f"Feature flag '{flag_name}' is disabled. "
            "Set the corresponding environment variable to enable it."
        )
