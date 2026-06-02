"""Debate domain models — multi-perspective analysis with reconciliation.

Phase 3 — Opposing-Viewpoints Synthesis.  Spawns agents with deliberately
different perspectives (optimist, pessimist, pragmatist), each researches
independently, and a reconciler identifies consensus, dissent, and blind spots.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Viewpoint(BaseModel):
    """A single perspective in a debate."""

    role: str = Field(default="", description="'optimist' | 'pessimist' | 'pragmatist'")
    research_findings: str = Field(default="")
    key_claims: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DebateResult(BaseModel):
    """Synthesized result from opposing viewpoints."""

    question: str = Field(default="")
    viewpoints: list[Viewpoint] = Field(default_factory=list)
    consensus: list[str] = Field(
        default_factory=list,
        description="Points all viewpoints agree on",
    )
    dissent: list[dict] = Field(
        default_factory=list,
        description="[{'topic': ..., 'optimist': ..., 'pessimist': ...}]",
    )
    blind_spots: list[str] = Field(
        default_factory=list,
        description="Important angles no viewpoint covered",
    )
    synthesis: str = Field(default="", description="Final balanced analysis")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
