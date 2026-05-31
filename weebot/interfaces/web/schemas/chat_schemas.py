"""Chat REST API schemas — request and response Pydantic models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request to send a chat message."""
    message: str = Field(min_length=1, max_length=10000)
    model: str = Field(default="", description="Model to use (empty = session default)")
    session_id: str | None = Field(default=None, description="Resume an existing session")


class ChatResponse(BaseModel):
    """Response from a chat message turn."""
    session_id: str
    message: str
    role: str = "assistant"
    model: str
    tokens_used: int = 0
    cost: float = 0.0
    exchange_count: int = 0


class ChatSessionSummary(BaseModel):
    """Summary of a chat session for listing."""
    id: str
    status: str
    message_count: int
    total_tokens: int
    total_cost: float
    created_at: str


class ChatSessionList(BaseModel):
    """List of chat sessions."""
    sessions: list[ChatSessionSummary]
    total: int
