"""Request schemas for web API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

_SESSION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    prompt: str = Field(..., description="Initial user prompt")
    user_id: str = Field(default="web-user", description="User identifier")
    agent_id: str = Field(default="weebot-web", description="Agent identifier")
    model: str | None = Field(default=None, description="LLM model to use")
    session_id: str | None = Field(
        default=None, description="Optional custom session ID", pattern=_SESSION_ID_PATTERN
    )
    ponytail_mode: str | None = Field(
        default=None,
        description="Optional Ponytail lazy-senior-dev mode: off | lite | full | ultra",
    )


class SendMessageRequest(BaseModel):
    """Request to send a message to an existing session."""

    message: str = Field(..., description="User message")


class ResumeSessionRequest(BaseModel):
    """Request to resume a waiting session with user answer."""

    answer: str = Field(..., description="User answer to HITL question")


class UpdateSessionRequest(BaseModel):
    """Request to update session settings."""

    title: str | None = Field(default=None, description="Session title")
    context: dict[str, Any] | None = Field(default=None, description="Session context")


class SessionInputRequest(BaseModel):
    """Request to the unified /sessions/{id}/input endpoint.

    One shape for all four verbs (start/resume/steer/chat) — the backend
    resolves which applies from the session's current status. See
    ``application/use_cases/dispatch_session_input.py``.
    """

    text: str = Field(
        ..., min_length=1, description="User text — prompt, answer, steer message, or chat turn"
    )
    client_msg_id: str | None = Field(
        default=None, description="Client-generated id for optimistic-UI reconciliation"
    )
    model: str | None = Field(default=None, description="LLM model override (chat/start only)")
