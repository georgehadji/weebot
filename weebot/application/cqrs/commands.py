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


class CompactMemoryCommand(Command):
    """Command to compact session memory."""
    session_id: str = Field(min_length=1)
    target_tokens: int = 4000

    def validate(self) -> None:
        if self.target_tokens < 1000:
            raise ValueError("target_tokens must be at least 1000")


class CancelSessionCommand(Command):
    """Command to cancel an active session."""
    session_id: str = Field(min_length=1)
    reason: str = ""


class ArchiveSessionCommand(Command):
    """Command to archive a completed session."""
    session_id: str = Field(min_length=1)
    ttl_days: int = 30

    def validate(self) -> None:
        if self.ttl_days < 1:
            raise ValueError("ttl_days must be at least 1")


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
CompactMemoryCommand.model_rebuild()
CancelSessionCommand.model_rebuild()
ArchiveSessionCommand.model_rebuild()
ProcessMessageCommand.model_rebuild()
