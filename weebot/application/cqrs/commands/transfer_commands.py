"""Cross-Model Transfer CQRS command — evaluate a skill on a different model/harness."""
from __future__ import annotations

from pydantic import Field

from weebot.application.cqrs.base import Command


class ValidateTransferCommand(Command):
    """Evaluate a skill on a target (model, harness) pair and report the score delta.

    The handler runs validation tasks twice — once with no skill (baseline)
    and once with the skill injected as a system prompt — to measure transfer.
    """
    skill_name: str = Field(min_length=1)
    target_model: str = Field(min_length=1, description="e.g., 'openai/gpt-5.4-mini'")
    target_harness: str = Field(default="direct_chat", description="e.g., 'direct_chat' | 'codex' | 'claude_code'")
    validation_tasks: list[str] = Field(
        default_factory=list,
        description="Task prompts for held-out validation split",
    )

    def validate(self) -> None:
        if not self.validation_tasks:
            raise ValueError("validation_tasks must not be empty")
        if not self.target_model:
            raise ValueError("target_model is required")
