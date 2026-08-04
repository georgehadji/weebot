"""Pre-built commands for Weebot operations (Pydantic models).

Migration note:  Commands now use Pydantic BaseModel instead of
@dataclass(frozen=True).  Field-level validation is baked into the
model via Field(min_length=...) etc., and the hand-written validate()
methods are preserved for custom business-rule logic.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from weebot.application.cqrs.base import Command
from weebot.config.model_refs import MODEL_COMMAND_DEFAULT


class CreatePlanCommand(Command):
    """Command to create a new plan."""
    session_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    model: str = MODEL_COMMAND_DEFAULT
    context: dict[str, Any] = Field(default_factory=dict)
    meta_notes: list[str] = Field(
        default_factory=list,
        description="Cross-session avoidance hints from MisalignmentJournal",
    )


class ExecuteStepCommand(Command):
    """Command to execute a plan step."""
    session_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    model: str = ""
    tools: list[str] = []


class UpdatePlanCommand(Command):
    """Command to update an existing plan."""
    session_id: str = Field(min_length=1)
    updates: dict[str, Any]
    reason: str = ""
    model: str = ""

    def validate(self) -> None:
        if not self.updates:
            raise ValueError("updates is required")


class SummarizeCommand(Command):
    """Command to generate a final summary for a completed session."""
    session_id: str = Field(min_length=1)


class ProcessMessageCommand(Command):
    """Command to process a chat message through the LLM.

    Attributes:
        session_id: The chat session identifier.
        message: The user's message text.
        model: Model to use for the response (defaults to session model).
        history: Previous conversation messages serialised as dicts.
        exchange_count: How many exchanges have occurred so far.
    """
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    model: str = ""
    history: list[dict[str, str]] = Field(default_factory=list)
    exchange_count: int = 0


# Rebuild models with forward references resolved.
# Required because from __future__ import annotations makes all annotations
# strings, and Pydantic needs to resolve dict[str, Any] at runtime.
CreatePlanCommand.model_rebuild()
ExecuteStepCommand.model_rebuild()
UpdatePlanCommand.model_rebuild()
SummarizeCommand.model_rebuild()
ProcessMessageCommand.model_rebuild()
