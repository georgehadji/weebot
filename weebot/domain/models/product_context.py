"""ProductContext — product-thinking metadata for a task.

Captures the pre-flight checklist from product-mode before any plan is
created. Stored in session.context.extra["product_context"] and referenced
by the planner, verifier, and decision log.

product-mode reference:
    https://github.com/sohaibt/product-mode
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProductAssumption(BaseModel):
    """A single assumption with its validation status.

    Each assumption is tagged with whether it has been validated by data,
    reasonably assumed, or is unknown and needs verification.
    """
    text: str = Field(default="", description="The assumption statement")
    status: str = Field(
        default="unknown",
        description="'validated' | 'assumed' | 'unknown'",
    )


class ProductContext(BaseModel):
    """Pre-flight product thinking for a non-trivial task.

    Filled by ProductGateAnalyzer before the planner runs.
    Follows product-mode's pre-flight checklist:

        - Problem: Whose pain are we solving, in one sentence?
        - Why now: What changed? Evidence, trigger, cost of waiting.
        - Scope: Smallest change that tests the hypothesis.
        - Success metric: The one number we expect to move.
        - Reversibility: One-way or two-way door?
    """

    # ── Pre-flight checklist (product-mode Principles 1-5) ─────────
    problem: str = Field(
        default="",
        description="Whose pain are we solving, in one sentence?",
    )
    why_now: str = Field(
        default="",
        description="What changed? Evidence, trigger, cost of waiting.",
    )
    scope: str = Field(
        default="",
        description="Smallest change that tests the hypothesis.",
    )
    success_metric: str = Field(
        default="",
        description="The one number or observable we expect to move.",
    )
    reversibility: Literal["one-way", "two-way"] = Field(
        default="two-way",
        description="'one-way' (costly to undo) or 'two-way' (easily reversible).",
    )

    # ── Assumptions (Principle 2) ──────────────────────────────────
    assumptions: list[ProductAssumption] = Field(
        default_factory=list,
        description="Assumptions the plan depends on, each with validation status.",
    )

    # ── Meta ───────────────────────────────────────────────────────
    overall_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="LLM's confidence that the problem framing is correct.",
    )
    generated_at: str = Field(
        default="",
        description="ISO-8601 timestamp of when this context was created.",
    )
    model_used: str = Field(
        default="",
        description="Model ID used to produce this analysis.",
    )
