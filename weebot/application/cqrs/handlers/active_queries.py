"""Query handlers for session, plan, and meta queries.

Split from query_handlers.py during architecture remediation.
"""
from __future__ import annotations

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.application.models.tool_collection import ToolCollection

from weebot.application.cqrs.queries import (
    GetActiveTasksQuery,
    GetActiveSessionsQuery,
    GetCostSummaryQuery,
)

class GetActiveTasksHandler(QueryHandler):
    """Get currently active/running tasks."""

    def __init__(self, task_runner: TaskRunner):
        self._task_runner = task_runner

    async def handle(self, query: GetActiveTasksQuery) -> QueryResult:
        try:
            active_ids = await self._task_runner.list_active_sessions() if self._task_runner else []

            limited = active_ids[: query.limit]
            return QueryResult.ok({
                "active_tasks": [
                    {"session_id": sid, "status": "running"}
                    for sid in limited
                ],
                "total": len(active_ids),
                "limit": query.limit,
            })
        except Exception as exc:
            return QueryResult.fail(str(exc))


# ── Operations Console handlers (Enhancement 4) ───────────────────────


class GetActiveSessionsHandler(QueryHandler):
    """List all running sessions with flow state, step count, and tool call count."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetActiveSessionsQuery) -> QueryResult:
        try:
            sessions = await self._state_repo.list_sessions(status="running")
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
