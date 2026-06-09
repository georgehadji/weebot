"""Built-in task preset registry.

Three tiers mirroring Reasoner's Budget / Balanced / Premium pattern.
Presets are pure data — no LLM calls or I/O at import time.
"""
from __future__ import annotations

from weebot.domain.models.task_preset import TaskPreset

PRESET_SIMPLE = TaskPreset(
    name="simple",
    enable_premortem=False,
    enable_step_validation=False,
    critique_warn_threshold=0.6,   # Less strict — simple tasks rarely fail
    critique_revise_threshold=0.3,
    max_steps=10,
    notes="Greetings, factual lookups, single-tool tasks. Minimal overhead.",
)

PRESET_STANDARD = TaskPreset(
    name="standard",
    enable_premortem=False,
    enable_step_validation=True,
    critique_warn_threshold=0.8,
    critique_revise_threshold=0.5,
    max_steps=None,  # flow default
    notes="Multi-step tasks with moderate risk. Default tier.",
)

PRESET_COMPLEX = TaskPreset(
    name="complex",
    enable_premortem=True,
    enable_step_validation=True,
    critique_warn_threshold=0.85,  # Stricter — high-stakes tasks
    critique_revise_threshold=0.6,
    max_steps=None,
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
