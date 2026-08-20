"""TaskPreset — declarative cost/quality configuration for a task run.

Pure domain model: no imports from Application or Infrastructure.
Presets are selected by the pre-router based on task complexity and
injected into PlanActFlowConfig at flow construction time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class AuditDepth(IntEnum):
    """How much verification a step's evidence gets — LongHorizon-Harness E5.

    Ordered so a preset can compare depth with < / >=. Tier 0 (EVIDENCE_ONLY)
    is the mechanical, zero-model-call check (E1) and runs unconditionally;
    ACCEPTANCE and FULL_AUDIT are progressively more expensive and are what
    the preset actually gates.
    """

    EVIDENCE_ONLY = 0
    ACCEPTANCE = 1
    FULL_AUDIT = 2


@dataclass(frozen=True)
class TaskPreset:
    """Immutable configuration for a single task execution tier.

    Fields:
        name:               Human-readable identifier ("simple", "standard", "complex").
        enable_premortem:   Whether to run PremortmState before execution.
        enable_step_validation: Whether to run StepResultValidator in the executor.
        critique_warn_threshold: Override for CritiquingState.WARN_THRESHOLD (default 0.8).
        critique_revise_threshold: Override for CritiquingState.REVISE_THRESHOLD (default 0.5).
        max_steps:          Step budget override (None = use flow default).
        role_model_overrides: dict[role -> model_id] — overrides ROLE_MODEL_CONFIG entries.
        audit_depth:        How deep step verification goes (LongHorizon-Harness E5).
        notes:              Human-readable rationale (not used at runtime).
    """

    name: str
    enable_premortem: bool = False
    enable_step_validation: bool = True
    critique_warn_threshold: float = 0.8
    critique_revise_threshold: float = 0.5
    max_steps: int | None = None
    role_model_overrides: dict[str, str] = field(default_factory=dict)
    audit_depth: AuditDepth = AuditDepth.ACCEPTANCE
    notes: str = ""
