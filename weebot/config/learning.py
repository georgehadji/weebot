"""Deployment-time learning configuration (Memento-Skills plan, Phase 0).

Central home for the thresholds that govern live skill distillation,
retrieval-miss detection, deduplication, and trust promotion. Feature
flags themselves live in :mod:`weebot.config.feature_flags`; they are
re-exported here so callers have a single import for the learning subsystem.
"""

from __future__ import annotations

from weebot.config.feature_flags import (  # noqa: F401  (re-export)
    CURATION_ACTIONS_ENABLED,
    LIVE_SKILL_DISTILLATION_ENABLED,
    ONLINE_SKILLOPT_ENABLED,
    SEMANTIC_SKILL_RETRIEVAL_ENABLED,
    SKILL_GAP_TRIGGER_ENABLED,
)

# Minimum rerank score for a retrieved skill to be injected live.
# Mirrors the existing literal in executor/_base.py (Tier 1.2 injection gate).
TAU_INJECT: float = 0.15

# Best-match score at/above which retrieval is considered a "hit". Below this,
# the step is treated as a retrieval miss and may raise a skill-gap signal (R2).
TAU_CREATE: float = 0.35

# Similarity at/above which a distilled candidate is deemed a duplicate of an
# existing skill; the loop reinforces the existing skill instead of creating one.
TAU_DEDUP: float = 0.80

# Validated positive uses required to promote a skill candidate -> trusted.
CANDIDATE_PROMOTION_USES: int = 3

# Guardrail against silent drift from fully-automatic promotion (both
# quarantined->candidate via SkillReviewGate and candidate->trusted via
# ValidateSkillHandler.record_positive_use): once this many promotions have
# happened through a given process's lifetime, further promotions that would
# otherwise pass are logged and withheld rather than applied. Not a hard cap
# on skill creation or validation — only on trust-tier promotion.
MAX_SKILL_PROMOTIONS_PER_RUN: int = 20

__all__ = [
    "TAU_INJECT",
    "TAU_CREATE",
    "TAU_DEDUP",
    "CANDIDATE_PROMOTION_USES",
    "MAX_SKILL_PROMOTIONS_PER_RUN",
    "LIVE_SKILL_DISTILLATION_ENABLED",
    "SKILL_GAP_TRIGGER_ENABLED",
    "SEMANTIC_SKILL_RETRIEVAL_ENABLED",
    "CURATION_ACTIONS_ENABLED",
    "ONLINE_SKILLOPT_ENABLED",
]
