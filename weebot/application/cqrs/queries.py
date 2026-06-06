"""Pre-built queries for Weebot data retrieval (Pydantic models)."""
from __future__ import annotations

from pydantic import Field

from weebot.application.cqrs.base import Query


class GetSessionQuery(Query):
    """Get a session by ID."""
    session_id: str = Field(min_length=1)
    include_events: bool = True


class ListSessionsQuery(Query):
    """List sessions with optional filtering."""
    user_id: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.limit > 1000:
            raise ValueError("limit cannot exceed 1000")
        if self.offset < 0:
            raise ValueError("offset cannot be negative")


class GetSessionHistoryQuery(Query):
    """Get the event history of a session."""
    session_id: str = Field(min_length=1)
    event_types: list[str] = []
    limit: int = 100
    offset: int = 0

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.limit > 10000:
            raise ValueError("limit cannot exceed 10000")
        if self.offset < 0:
            raise ValueError("offset cannot be negative")


class GetActiveTasksQuery(Query):
    """Get currently active tasks."""
    limit: int = 100

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")


class GetSessionStatusQuery(Query):
    """Get the current status of a session."""
    session_id: str = Field(min_length=1)


class GetPlanQuery(Query):
    """Get the current plan for a session."""
    session_id: str = Field(min_length=1)
    include_completed_steps: bool = True


class SearchSessionsQuery(Query):
    """Search sessions by content."""
    query: str = Field(min_length=1)
    user_id: str | None = None
    limit: int = 20

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.limit > 100:
            raise ValueError("limit cannot exceed 100")


class GetSimilarSessionsQuery(Query):
    """Find sessions similar to a given session."""
    session_id: str = Field(min_length=1)
    limit: int = 5

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")


# ── Operations Console queries (Enhancement 4) ────────────────────────


class GetActiveSessionsQuery(Query):
    """List all currently running sessions with status, flow state, and cost.

    Used by the operations console dashboard (GET /api/sessions/active).
    """
    limit: int = 100

    def validate(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.limit > 500:
            raise ValueError("limit cannot exceed 500")


class GetPlanVisualizationQuery(Query):
    """Return plan DAG node/edge data for a session's current plan.

    Used by the plan visualizer (GET /api/sessions/{id}/plan-viz).
    """
    session_id: str = Field(min_length=1)


class GetCostSummaryQuery(Query):
    """Aggregate cost and cascade stats for a time window.

    Used by the cost dashboard (GET /api/costs/summary).
    """
    window_hours: int = 24

    def validate(self) -> None:
        if self.window_hours < 1:
            raise ValueError("window_hours must be at least 1")
        if self.window_hours > 720:
            raise ValueError("window_hours cannot exceed 720 (30 days)")
