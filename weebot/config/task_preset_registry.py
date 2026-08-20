"""Built-in task preset registry.

Three tiers mirroring Reasoner's Budget / Balanced / Premium pattern.
Presets are pure data — no LLM calls or I/O at import time.
"""

from __future__ import annotations

from weebot.domain.models.task_preset import AuditDepth, TaskPreset
from weebot.domain.models.task_route import TaskCategory, TaskComplexity, TaskRoute

PRESET_SIMPLE = TaskPreset(
    name="simple",
    enable_premortem=False,
    enable_step_validation=False,
    critique_warn_threshold=0.6,  # Less strict — simple tasks rarely fail
    critique_revise_threshold=0.3,
    max_steps=10,
    audit_depth=AuditDepth.EVIDENCE_ONLY,
    notes="Greetings, factual lookups, single-tool tasks. Minimal overhead.",
)

PRESET_STANDARD = TaskPreset(
    name="standard",
    enable_premortem=False,
    enable_step_validation=True,
    critique_warn_threshold=0.8,
    critique_revise_threshold=0.5,
    max_steps=None,  # flow default
    audit_depth=AuditDepth.ACCEPTANCE,
    notes="Multi-step tasks with moderate risk. Default tier.",
)

PRESET_COMPLEX = TaskPreset(
    name="complex",
    enable_premortem=True,
    enable_step_validation=True,
    critique_warn_threshold=0.85,  # Stricter — high-stakes tasks
    critique_revise_threshold=0.6,
    max_steps=None,
    audit_depth=AuditDepth.FULL_AUDIT,
    notes="Architectural changes, long pipelines, high-risk operations.",
)

_REGISTRY: dict[str, TaskPreset] = {
    p.name: p for p in (PRESET_SIMPLE, PRESET_STANDARD, PRESET_COMPLEX)
}


def get_preset(name: str) -> TaskPreset:
    """Return a preset by name, falling back to PRESET_STANDARD."""
    return _REGISTRY.get(name, PRESET_STANDARD)


def register_preset(preset: TaskPreset) -> None:
    """Register a custom preset (useful for tests and extensions)."""
    _REGISTRY[preset.name] = preset


def select_preset(route: TaskRoute) -> TaskPreset:
    """Map a router decision to a cost/quality tier — LongHorizon-Harness E5.

    Policy lives here, beside the registry it reads from (C2) — not in
    interfaces/factories.py, which only wires the result through.
    """
    if route.complexity is TaskComplexity.LOW:
        return PRESET_SIMPLE
    if route.category is TaskCategory.COMPLEX:
        return PRESET_COMPLEX
    return PRESET_STANDARD
