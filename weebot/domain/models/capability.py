"""Capability domain models — quality axes, model profiles, task requirements.

Part of the Adaptive Capability Router (ACR) — Phase P1.

Quality axes represent *capabilities* (what a model is good at), not penalties
(cost, latency) which are handled as separate terms in the utility function.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CapabilityAxis(str, Enum):
    """Quality dimensions for model capability profiling.

    These are the axes used in the cosine-similarity match between a model's
    quality profile and a task's requirement vector.  Cost, latency, and
    context-window are NOT capabilities — they are penalties/constraints and
    live in ModelInfo / the Constraint Checker.
    """
    REASONING = "reasoning"
    CODING = "coding"
    WRITING = "writing"
    LEGAL = "legal"
    MATH = "math"
    CITATION = "citation"
    PLANNING = "planning"
    TOOL_USE = "tool_use"
    LONG_CONTEXT = "long_context"


class ModelQualityProfile(BaseModel):
    """Benchmark- or telemetry-derived quality scores for a model.

    Immutable — once created, never mutated.  Scores are on a 0..10 scale
    where higher is better.

    The ``source`` field tracks provenance so consumers can distinguish
    hand-authored seeds from live telemetry measurements.
    """
    model_config = ConfigDict(frozen=True)

    # Pydantic v2's frozen hash can't handle dict fields — use object's hash instead.
    __hash__ = object.__hash__

    model_id: str = Field(
        description="Full model identifier (e.g. 'deepseek/deepseek-v4-flash')",
    )
    axes: dict[CapabilityAxis, float] = Field(
        default_factory=dict,
        description="Quality scores per axis (0..10).  Only capability axes — "
                    "no cost, latency, or context fields.",
    )
    source: Literal["benchmark", "telemetry", "seed"] = Field(
        default="seed",
        description="Provenance of the profile data.",
    )


class TaskRequirement(BaseModel):
    """Capability requirements and utility coefficients for a task category.

    Two roles in the ACR pipeline:

    1. **Hard-gate input:** ``requires_vision``, ``requires_tools``, and
       ``min_context`` are used by the Constraint Checker to filter ineligible
       models before scoring.

    2. **Scorer input:** ``quality_weights`` are the target vector for cosine
       similarity with ``ModelQualityProfile.axes``.  ``utility_coeff``
       provides the ``(α, β, δ, ε)`` weights for the linear combination
       ``U = α·cap_match + β·quality − δ·cost − ε·latency``.
    """
    model_config = ConfigDict(frozen=True)

    # Pydantic v2's frozen hash can't handle dict fields — use object's hash instead.
    __hash__ = object.__hash__

    # ── Hard-gate flags ─────────────────────────────────────────────
    requires_vision: bool = Field(
        default=False,
        description="Step requires a vision-capable model.",
    )
    requires_tools: bool = Field(
        default=True,
        description="Step requires function/tool calling support.",
    )
    min_context: int = Field(
        default=0,
        description="Minimum context window (input tokens) required.",
    )

    # ── Quality match weights (cap_match vector) ────────────────────
    quality_weights: dict[CapabilityAxis, float] = Field(
        default_factory=lambda: {
            CapabilityAxis.REASONING: 1.0,
            CapabilityAxis.CODING: 1.0,
            CapabilityAxis.TOOL_USE: 1.0,
        },
        description="Weight per capability axis — forms the requirement "
                    "vector for cosine match against ModelQualityProfile.axes. "
                    "Axes not listed default to 0.0 (irrelevant for this task).",
    )

    # ── Utility function coefficients ───────────────────────────────
    utility_coeff: dict[str, float] = Field(
        default_factory=lambda: {"alpha": 0.4, "beta": 0.3, "delta": 0.2, "epsilon": 0.1},
        description="Coefficients (α, β, δ, ε) for the combo utility function. "
                    "Must sum to 1.0 within floating-point tolerance.",
    )
