"""Feature flags for weebot — gating experimental or high-risk capabilities.

Each flag defaults to OFF.  Flags should be toggled via environment variables
or a config file, never hardcoded to True in production.

HyperAgents Enhancement 7: METACOGNITIVE_IMPROVEMENT_ENABLED controls whether
the SelfImprover can edit its own prompt and allowlist (self-referential
improvement).  Default OFF — requires explicit opt-in.
"""

from __future__ import annotations

import os


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
LIVE_SKILL_DISTILLATION_ENABLED: bool = _env_bool("WEEBOT_LIVE_SKILL_DISTILLATION", default=False)
# Phase 2 — on a retrieval miss, enqueue a gated skill-creation request.
SKILL_GAP_TRIGGER_ENABLED: bool = _env_bool("WEEBOT_SKILL_GAP_TRIGGER", default=False)
# Phase 3 — add a semantic (embedding) first stage to skill retrieval.
SEMANTIC_SKILL_RETRIEVAL_ENABLED: bool = _env_bool("WEEBOT_SEMANTIC_SKILL_RETRIEVAL", default=False)
# Phase 3b — replace keyword task router with embedding-based classification.
WEEBOT_SEMANTIC_TASK_ROUTER: bool = _env_bool("WEEBOT_SEMANTIC_TASK_ROUTER", default=False)
# Phase 4 — let the curator act (archive) and validate/dedup imports.
CURATION_ACTIONS_ENABLED: bool = _env_bool("WEEBOT_CURATION_ACTIONS", default=False)
# Phase 5 — attribute live failures to a skill and run online SkillOpt.
ONLINE_SKILLOPT_ENABLED: bool = _env_bool("WEEBOT_ONLINE_SKILLOPT", default=False)
# Phase 1b — LLM-judged review that promotes a freshly-distilled skill from
# quarantined -> candidate (SkillReviewGate). Without this, every skill
# LIVE_SKILL_DISTILLATION_ENABLED distils sits quarantined forever, since
# nothing else in production ever moves a skill off that tier.
SKILL_REVIEW_GATE_ENABLED: bool = _env_bool("WEEBOT_SKILL_REVIEW_GATE", default=False)
# Phase 1c — materialize a 'trusted' skill to disk as SKILL.md and refresh
# the live retriever's index (MaterializingSkillStore), so a skill promoted
# all the way to trusted becomes retrievable in the same process instead of
# only on the next restart.
SKILL_MATERIALIZE_ENABLED: bool = _env_bool("WEEBOT_SKILL_MATERIALIZE", default=False)


# ── Product-Mode (product-led thinking pipeline) ──────────────────────────
# Master switch for the product thinking enhancements:
# Planner prompt augmentation, ProductGateState, outcome verification.
# Default OFF — enable via WEEBOT_PRODUCT_MODE=true
PRODUCT_MODE_ENABLED: bool = _env_bool("WEEBOT_PRODUCT_MODE", default=False)
# When True, emit ProductDecisionEvent on session completion for non-trivial
# tasks with ProductContext available.
PRODUCT_DECISION_LOG_ENABLED: bool = _env_bool("WEEBOT_PRODUCT_DECISION_LOG", default=False)


# ── Vision-in-the-loop (PicoAgents audit) ───────────────────────────────────
# When True, tool results carrying a screenshot (ToolResult.base64_image) are
# injected back into the conversation as an image message, so a vision-capable
# model can *see* the browser/desktop state instead of driving it blind off DOM
# text + OCR. Only the most recent screenshot is kept live (token control).
# Plan: tasks/specs/picoagents_vision_in_loop_spec.md
VISION_IN_LOOP_ENABLED: bool = _env_bool("WEEBOT_VISION_IN_LOOP", default=True)

# Phase 2 reflection: after screenshot injection, make a structured LLM call to produce
# PageObservation + NextActionPlan JSON. Adds one extra LLM round-trip per screenshot.
# Requires VISION_IN_LOOP_ENABLED=True and a vision-capable model.
# COST: with both flags on, each screenshot is sent twice — once in the reflection
# call here, and once in the buffer that the next main call reads — so expect ~2x
# image tokens plus the extra round-trip. Keep off unless reflection earns its cost.
# Plan: tasks/specs/picoagents_vision_in_loop_spec.md (Phase 2)
VISION_REFLECTION_ENABLED: bool = _env_bool("WEEBOT_VISION_REFLECTION", default=True)


# ── Knowledge-graph extraction in the execution loop ────────────────────────
# When True, PlanActFlow receives the KnowledgeGraphService and the hook in
# ExecutingState upserts a node for every ``key: value`` line of every step
# result.  Extraction is a pure heuristic (no LLM call), but it is chatty: one
# SQLite write per matching line, on every step.  Default OFF — enable once you
# actually want the graph populated.
KNOWLEDGE_GRAPH_EXTRACTION_ENABLED: bool = _env_bool(
    "WEEBOT_KNOWLEDGE_GRAPH_EXTRACTION", default=False
)


# ── LongHorizon-Harness E7b: workspace integrity guard ──────────────────────
# When True, VerifyingState snapshots the workspace before the verification
# episode and diffs it after, reporting any change as an
# AuditDimension.INTEGRITY violation ("the audit modified what it audited").
#
# Default OFF, on measured cost rather than principle: a scan of this repo is
# ~2000 files and takes ~1.5s, and the guard runs two of them, so it adds ~3s
# to every verification episode. Today the verifier passes no tools and the
# auditor only reads through FileStoragePort — both pinned by
# tests/unit/test_verifier_readonly_tripwire.py — so the guard has nothing to
# catch and that 3s buys nothing.
#
# Turn this ON the moment that tripwire test fails: at that point the verifier
# CAN write, and the guard stops being decorative.
WORKSPACE_INTEGRITY_GUARD_ENABLED: bool = _env_bool(
    "WEEBOT_WORKSPACE_INTEGRITY_GUARD", default=False
)


# ── B2. OpenTelemetry tracing (ARCH-AUDIT-V2) ───────────────────────────────
# When True, PlanActFlow and ExecutorAgent create OTEL spans.  Default OFF
# until an OTEL collector endpoint is configured.
OTEL_TRACING_ENABLED: bool = _env_bool("WEEBOT_OTEL_TRACING", default=False)


# ── Adaptive Capability Router (ACR) — Phase P1+ ────────────────────────────
# Master switch: when True, the static task_model_router is replaced by the
# ACR pipeline: classify → constrain → score → (optional bandit) → ordered list.
# Default OFF until P4 GA.
WEEBOT_ENABLE_ACR: bool = _env_bool("WEEBOT_ENABLE_ACR", default=False)
# When True, the bandit stage (Thompson sampling) is enabled inside the ACR.
# Requires WEEBOT_ENABLE_ACR=True.  When False, ACR uses deterministic scoring.
WEEBOT_ACR_BANDIT: bool = _env_bool("WEEBOT_ACR_BANDIT", default=False)
# Shadow mode: when True, ACR logs its routing decisions but the static router
# still controls execution.  Useful for offline comparison during rollout.
WEEBOT_ACR_SHADOW: bool = _env_bool("WEEBOT_ACR_SHADOW", default=False)

# ── Memory snapshot cap (AgeMem fix plan, Phase 4 / A1a) ────────────────────
# When True, PersistentMemoryTool.load_snapshot() caps AGENT.md to the newest
# N entries plus a character budget instead of concatenating the whole file
# into every system prompt uncapped. Ranked by recency (file order), not
# salience — memory_metadata is frequently empty (a fresh install, or right
# after the F1 fix ships) and salience-ranking an empty-scored corpus
# degenerates into arbitrary truncation. Default OFF: only worth it once
# real memory content, not test litter, has grown past the cap.
MEMORY_SNAPSHOT_CAP_ENABLED: bool = _env_bool("WEEBOT_MEMORY_SNAPSHOT_CAP", default=False)


# ── C2. Durable task queue backend (ARCH-AUDIT-V2) ──────────────────────────
# Controls which queue backend the TaskRunner uses.
#   "memory" (default) — asyncio.PriorityQueue, non-durable, no external deps.
#   "redis"            — Redis Streams, durable, requires a running Redis instance.
WEEBOT_QUEUE_BACKEND: str = os.environ.get("WEEBOT_QUEUE_BACKEND", "memory").strip().lower()


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
