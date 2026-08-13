"""CorrectionRecord domain model — tracks output edits for source-level fixes.

Implements the ICM "edit-source principle": editing a step's output fixes
that one run; tracing a *recurring* edit pattern back to its source (a skill,
a planner rule, a behavioral rule) fixes every future run. This model is the
unit of record; ``CorrectionTracker`` (application layer) accumulates them
and detects recurring categories.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class CorrectionRecord(BaseModel):
    """Records the delta between a step's original output and its correction.

    "Original" is whatever the step produced before a replan/retry replaced
    it; "corrected" is the output that followed. A single record is just
    data — significance comes from accumulation: when the same
    ``correction_category`` recurs across records, it signals a fixable
    source-level problem rather than a one-off.
    """
    model_config = {"frozen": True}

    session_id: str
    step_id: str
    step_description: str
    original_output: str = Field(description="Step output before correction/replan")
    corrected_output: str = Field(description="Step output after successful re-execution")
    correction_category: str = Field(
        default="",
        description="Classified kind of edit: tone, format, scope, accuracy, "
                    "or missing_info.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
