"""Query handlers for the Operations Console.

Scope note (2026-08-04 pre-existing-architecture-debt audit, RC-1):
``GetActiveTasksHandler`` previously lived here but had no dispatch site
anywhere in the codebase; it was removed along with GetActiveTasksQuery.
Both handlers below are live — dispatched by
``interfaces/web/routers/ops_router.py``.
"""

from __future__ import annotations

import logging

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.ports.event_store_port import EventStorePort
from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.queries import GetActiveSessionsQuery, GetCostSummaryQuery

logger = logging.getLogger(__name__)


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
            sessions = await self._state_repo.list_sessions(user_id=query.user_id, status="running")
            limited = sessions[: query.limit]

            active = []
            for s in limited:
                plan = s.get_last_plan() if hasattr(s, "get_last_plan") else None
                step_count = len(plan.steps) if plan else 0
                completed = (
                    sum(
                        1
                        for st in plan.steps
                        if hasattr(st.status, "value") and st.status.value == "completed"
                    )
                    if plan
                    else 0
                )

                # Count tool calls from events
                tool_calls = sum(1 for e in s.events if hasattr(e, "type") and e.type == "tool")

                active.append(
                    {
                        "session_id": s.id,
                        "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                        "step_count": step_count,
                        "steps_completed": completed,
                        "tool_calls": tool_calls,
                        "elapsed_events": len(s.events),
                    }
                )

            return QueryResult.ok({"sessions": active, "total": len(active), "limit": query.limit})
        except Exception as exc:
            return QueryResult.fail(str(exc))


class GetCostSummaryHandler(QueryHandler):
    """The one cost query: LLM spend from the event store (W4.2, F23).

    Executors publish LLMCallCompleted (W4.1); DurableEventBus writes it with
    its cost columns. The CLI ``costs`` command, MCP ``weebot://costs`` and the
    ops API all answer through this handler.
    """

    def __init__(self, event_store: EventStorePort | None):
        self._event_store = event_store

    async def handle(self, query: GetCostSummaryQuery) -> QueryResult:
        if self._event_store is None:
            return QueryResult.fail("no event store configured")
        try:
            query.validate()
            summary = await self._event_store.get_cost_window(query.window_hours)
        except Exception as exc:
            logger.warning("cost summary failed: %s", exc)
            return QueryResult.fail(str(exc))
        summary["window_hours"] = query.window_hours
        return QueryResult.ok(summary)
