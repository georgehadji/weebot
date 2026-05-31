"""Request schemas for web API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""
    prompt: str = Field(..., description="Initial user prompt")
    user_id: str = Field(default="web-user", description="User identifier")
    agent_id: str = Field(default="weebot-web", description="Agent identifier")
    model: Optional[str] = Field(default=None, description="LLM model to use")
    session_id: Optional[str] = Field(default=None, description="Optional custom session ID")


class SendMessageRequest(BaseModel):
    """Request to send a message to an existing session."""
    message: str = Field(..., description="User message")


class ResumeSessionRequest(BaseModel):
    """Request to resume a waiting session with user answer."""
    answer: str = Field(..., description="User answer to HITL question")


class UpdateSessionRequest(BaseModel):
    """Request to update session settings."""
    title: Optional[str] = Field(default=None, description="Session title")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Session context")
