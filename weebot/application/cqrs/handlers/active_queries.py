"""Query handlers for the Operations Console.

Scope note (2026-08-04 pre-existing-architecture-debt audit, RC-1):
``GetActiveTasksHandler`` previously lived here but had no dispatch site
anywhere in the codebase; it was removed along with GetActiveTasksQuery.
Both handlers below are live — dispatched by
``interfaces/web/routers/ops_router.py``.
"""
from __future__ import annotations

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.queries import (
    GetActiveSessionsQuery,
    GetCostSummaryQuery,
)


class GetActiveSessionsHandler(QueryHandler):
    """List running sessions with flow state, step count, and tool call count."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetActiveSessionsQuery) -> QueryResult:
        try:
            # user_id is scoped deliberately: /api/sessions/active is
            # documented as returning only the caller's sessions, and
            # without this filter it returned every user's running
            # sessions.
            sessions = await self._state_repo.list_sessions(
                user_id=query.user_id, status="running",
            )
            limited = sessions[: query.limit]

            active = []
            for s in limited:
                plan = s.get_last_plan() if hasattr(s, "get_last_plan") else None
                step_count = len(plan.steps) if plan else 0
                completed = sum(
                    1 for st in plan.steps
                    if hasattr(st.status, "value") and st.status.value == "completed"
                ) if plan else 0

                # Count tool calls from events
                tool_calls = sum(
                    1 for e in s.events
                    if hasattr(e, "type") and e.type == "tool"
                )

                active.append({
                    "session_id": s.id,
                    "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                    "step_count": step_count,
                    "steps_completed": completed,
                    "tool_calls": tool_calls,
                    "elapsed_events": len(s.events),
                })

            return QueryResult.ok({
                "sessions": active,
                "total": len(active),
                "limit": query.limit,
            })
        except Exception as exc:
            return QueryResult.fail(str(exc))


class GetCostSummaryHandler(QueryHandler):
    """Aggregate cost/cascade stats from the cascade tracker."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetCostSummaryQuery) -> QueryResult:
        try:
            # Try to get cascade tracker from DI container
            try:
                from weebot.application.di import Container
                c = Container()
                c.configure_defaults()
                tracker = c.get("cascade_tracker")
                summary = tracker.summary() if tracker else {"total_decisions": 0}
            except Exception:
                summary = {
                    "total_decisions": 0,
                    "per_tier": {},
                    "total_cost_estimate": 0.0,
                    "avg_latency_ms": 0.0,
                    "cascade_hit_rate": 1.0,
                }

            summary["window_hours"] = query.window_hours
            return QueryResult.ok(summary)
        except Exception as exc:
            return QueryResult.fail(str(exc))
