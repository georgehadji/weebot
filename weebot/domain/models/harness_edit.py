"""HarnessEdit domain model — a proposed edit to a HarnessConfig surface.

Each edit is a single bounded change to one editable surface.  The
Self-Harness proposal stage produces multiple edits; the validation
gate promotes only edits that pass regression testing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class HarnessEdit(BaseModel):
    """A single bounded edit to one harness surface.

    Attributes:
        target_surface: Dot-separated path to the surface being edited
            (e.g. ``"instructions.bootstrap"``, ``"runtime_control.max_recent_tool_errors"``).
        old_value: The value before the edit.
        new_value: The value after the edit.
        targeted_mechanism: Which failure mechanism this edit addresses
            (from the Weakness Mining evidence bundle).
        expected_effect: Human-readable description of what should improve.
        regression_risks: Potential negative side-effects.
        validation_score: Score from regression testing (0.0–1.0).
        accepted: Whether the edit passed the regression gate.
    """

    target_surface: str = Field(
        description="Dot-separated path (e.g. 'instructions.bootstrap')",
    )
    old_value: str = Field(default="", description="Value before the edit")
    new_value: str = Field(default="", description="Value after the edit")
    targeted_mechanism: str = Field(
        default="",
        description="Failure mechanism this edit addresses",
    )
    expected_effect: str = Field(
        default="",
        description="What should improve",
    )
    regression_risks: list[str] = Field(
        default_factory=list,
        description="Potential negative side-effects",
    )
    validation_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Score from regression testing",
    )
    accepted: bool = Field(
        default=False,
        description="Whether the edit passed the regression gate",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def to_edit_dict(self) -> dict:
        """Convert to the dict format expected by HarnessOptimizationTarget.apply_edits()."""
        return {
            "target": self.target_surface,
            "value": self.new_value,
        }


class PromotionDecision(BaseModel):
    """Result of validating a set of harness edits.

    Attributes:
        accepted: Whether the candidate harness was promoted.
        delta_in: Performance change on held-in tasks.
        delta_ho: Performance change on held-out tasks.
        reason: Human-readable justification.
        edits: The edits that were proposed.
    """

    accepted: bool = Field(default=False)
    delta_in: float = Field(default=0.0)
    delta_ho: float = Field(default=0.0)
    reason: str = Field(default="")
    edits: list[HarnessEdit] = Field(default_factory=list)
