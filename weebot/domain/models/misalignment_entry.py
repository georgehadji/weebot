"""MisalignmentEntry — records a detected or user-corrected misalignment event."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class MisalignmentEntry(BaseModel):
    """An observed instance of agent-developer misalignment, for avoidance in future sessions."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(default="")
    project_path: str = Field(default="", description="Working directory, used to scope lookups")
    symptom: str = Field(
        default="",
        description="'constraint_violation' | 'user_correction' | 'scope_overreach'",
    )
    constraint_text: Optional[str] = Field(default=None, description="The violated constraint, if known")
    step_description: Optional[str] = Field(default=None, description="The step that triggered the issue")
    correction_text: Optional[str] = Field(default=None, description="What the user said to correct it")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
