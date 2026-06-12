"""Response schemas for web API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from weebot.domain.models.session import SessionStatus


class ErrorResponse(BaseModel):
    """Error response."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error information")


class SessionResponse(BaseModel):
    """Session response."""
    id: str = Field(..., description="Session ID")
    user_id: str = Field(..., description="User ID")
    agent_id: str = Field(..., description="Agent ID")
    status: str = Field(..., description="Session status")
    title: Optional[str] = Field(default=None, description="Session title")
    context: Dict[str, Any] = Field(default_factory=dict, description="Session context")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    event_count: int = Field(default=0, description="Number of events in session")


class SessionListResponse(BaseModel):
    """List of sessions response."""
    sessions: List[SessionResponse] = Field(default_factory=list)
    total: int = Field(..., description="Total number of sessions")


class ModelInfoResponse(BaseModel):
    """Model information response."""
    id: str = Field(..., description="Model ID")
    name: str = Field(..., description="Model display name")
    provider: str = Field(..., description="Model provider")
    cost_per_1k_tokens: float = Field(..., description="Cost per 1K tokens")
    context_window: int = Field(..., description="Context window size")
    tier: str = Field(..., description="Model tier (free/standard/premium)")
    strengths: List[str] = Field(default_factory=list, description="Model strengths")


class HealthComponent(BaseModel):
    """Health status of a single component."""
    name: str = Field(..., description="Component name")
    status: str = Field(..., description="Component status (healthy/degraded/unhealthy)")
    latency_ms: Optional[float] = Field(default=None, description="Response latency in ms")
    message: Optional[str] = Field(default=None, description="Status message")


class HealthResponse(BaseModel):
    """System health check response."""
    status: str = Field(..., description="Overall system status")
    components: List[HealthComponent] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    ws_token: Optional[str] = Field(
        default=None,
        description="WebSocket auth token (present when API key auth is enabled)",
    )


class MetricsResponse(BaseModel):
    """System metrics response."""
    total_sessions: int = Field(..., description="Total number of sessions")
    active_sessions: int = Field(..., description="Number of active sessions")
    completed_sessions: int = Field(..., description="Number of completed sessions")
    total_cost_usd: float = Field(..., description="Total cost in USD")
    model_usage: Dict[str, int] = Field(default_factory=dict, description="Usage per model")


class CostData(BaseModel):
    """Daily cost data."""
    date: str = Field(..., description="Date label")
    cost: float = Field(..., description="Cost for the day")
    tokens: int = Field(..., description="Token count for the day")


class ModelUsage(BaseModel):
    """Model usage statistics."""
    name: str = Field(..., description="Model name")
    cost: float = Field(..., description="Cost for this model")
    usage: int = Field(..., description="Number of calls")


class DashboardMetricsResponse(BaseModel):
    """Dashboard metrics response."""
    total_sessions: int = Field(default=0)
    active_sessions: int = Field(default=0)
    completed_sessions: int = Field(default=0)
    daily_costs: List[CostData] = Field(default_factory=list)
    model_usage: List[ModelUsage] = Field(default_factory=list)
    total_cost: float = Field(default=0.0)
    total_tokens: int = Field(default=0)
    cpu_usage: float = Field(default=0.0)
    memory_usage: float = Field(default=0.0)
    db_size: str = Field(default="0 MB")
    requests_per_minute: int = Field(default=0)
    avg_response_time: int = Field(default=0)
