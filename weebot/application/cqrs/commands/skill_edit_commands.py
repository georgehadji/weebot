"""CQRS commands for skill edit operations (Pydantic models)."""
from __future__ import annotations

from typing import Any

from pydantic import Field

from weebot.application.cqrs.base import Command


class ApplySkillEditsCommand(Command):
    """Apply bounded edits to a skill and run validation."""
    skill_name: str = Field(min_length=1)
    edits: list[dict[str, Any]] = []
    budget: int = 8
    validation_task_ids: list[str] = []
    context: dict[str, Any] = {}

    def validate(self) -> None:
        if self.budget < 0:
            raise ValueError("budget cannot be negative")
