"""Pre-built queries for Weebot data retrieval (Pydantic models).

Scope note (2026-08-04 pre-existing-architecture-debt audit, RC-1): the
session/plan/meta queries that previously lived here (GetSessionQuery,
ListSessionsQuery, GetSessionStatusQuery, GetSessionHistoryQuery,
SearchSessionsQuery, GetSimilarSessionsQuery, GetPlanQuery,
GetActiveTasksQuery) were registered on the mediator but had no dispatch
site anywhere in the codebase. They were removed along with their
handlers. What remains are the three Operations Console queries, which
are dispatched by ``interfaces/web/routers/ops_router.py``.
"""
from __future__ import annotations

from pydantic import Field

from weebot.application.cqrs.base import Query


# ── Operations Console queries (Enhancement 4) ────────────────────────


class GetActiveSessionsQuery(Query):
    """List all currently running sessions with status, flow state, and cost.

    Used by the operations console dashboard (GET /api/sessions/active).
    """
    user_id: str | None = None
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
