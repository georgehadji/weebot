"""CQRS commands for validation gate operations (Pydantic models)."""
from __future__ import annotations

from pydantic import Field

from weebot.application.cqrs.base import Command


class ValidateSkillCommand(Command):
    """Validate a candidate skill on held-out tasks."""
    skill_name: str = Field(min_length=1)
    candidate_content: str = Field(min_length=1)
    validation_task_ids: list[str] = []
    harness: str = "direct_chat"

    def validate(self) -> None:
        if not self.validation_task_ids:
            raise ValueError("validation_task_ids is required")
