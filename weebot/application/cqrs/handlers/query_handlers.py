"""Query handlers — read-only CQRS handlers for session queries.

Extracted from handlers.py to reduce that file from ~850 to ~460 lines.
"""
from __future__ import annotations

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.cqrs.queries import (
    GetSessionQuery,
    GetSessionStatusQuery,
    ListSessionsQuery,
    GetSessionHistoryQuery,
    GetPlanQuery,
    SearchSessionsQuery,
    GetSimilarSessionsQuery,
    GetActiveTasksQuery,
    GetActiveSessionsQuery,
    GetPlanVisualizationQuery,
    GetCostSummaryQuery,
)
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.application.models.tool_collection import ToolCollection


class GetSessionHandler(QueryHandler):
    """Retrieve a session by ID."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetSessionQuery) -> QueryResult:
        try:
            session = await self._state_repo.load_session(query.session_id)
            if session is None:
                return QueryResult.not_found("Session")

            data: dict = {
                "id": session.id,
                "user_id": session.user_id,
                "agent_id": session.agent_id,
                "status": session.status.value
                if hasattr(session.status, "value")
                else str(session.status),
                "created_at": session.created_at.isoformat()
                if hasattr(session, "created_at")
                else None,
            }

            if query.include_events:
                data["events"] = [
                    {
                        "type": type(e).__name__,
                        "timestamp": e.timestamp.isoformat()
                        if hasattr(e, "timestamp")
                        else None,
                    }
                    for e in session.events
                ]

            return QueryResult.ok(data)
        except Exception as exc:
            return QueryResult.fail(str(exc))


class ListSessionsHandler(QueryHandler):
    """List sessions with optional filtering."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: ListSessionsQuery) -> QueryResult:
        try:
            sessions = await self._state_repo.list_sessions(
                user_id=query.user_id,
                status=query.status,
                limit=query.limit,
                offset=query.offset,
            )

            data = {
                "sessions": [
                    {
                        "id": s.id,
                        "user_id": s.user_id,
                        "status": s.status.value
                        if hasattr(s.status, "value")
                        else str(s.status),
                    }
                    for s in sessions
                ],
                "limit": query.limit,
                "offset": query.offset,
                "total": len(sessions),
            }
            return QueryResult.ok(data)
        except Exception as exc:
            return QueryResult.fail(str(exc))


class GetSessionStatusHandler(QueryHandler):
    """Get the status of a session, including active task info."""

    def __init__(
        self,
        state_repo: StateRepositoryPort,
        task_runner: TaskRunner = None,
    ):
        self._state_repo = state_repo
        self._task_runner = task_runner

    async def handle(self, query: GetSessionStatusQuery) -> QueryResult:
        try:
            session = await self._state_repo.load_session(query.session_id)
            if session is None:
                return QueryResult.not_found("Session")

            data = {
                "session_id": query.session_id,
                "status": session.status.value
                if hasattr(session.status, "value")
                else str(session.status),
            }

            if self._task_runner:
                active = await self._task_runner.list_active_sessions()
                data["is_active"] = query.session_id in active

            return QueryResult.ok(data)
        except Exception as exc:
            return QueryResult.fail(str(exc))


class GetSessionHistoryHandler(QueryHandler):
    """Get the event history of a session with optional type filtering."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetSessionHistoryQuery) -> QueryResult:
        try:
            session = await self._state_repo.load_session(query.session_id)
            if session is None:
                return QueryResult.not_found("Session")

            events = [
                {
                    "type": type(e).__name__,
                    "timestamp": e.timestamp.isoformat()
                    if hasattr(e, "timestamp") else None,
                }
                for e in session.events
                if not query.event_types
                or type(e).__name__ in query.event_types
            ]

            total = len(events)
            paginated = events[query.offset : query.offset + query.limit]

            return QueryResult.ok({
                "session_id": query.session_id,
                "events": paginated,
                "total": total,
                "limit": query.limit,
                "offset": query.offset,
            })
        except Exception as exc:
            return QueryResult.fail(str(exc))


class GetPlanHandler(QueryHandler):
    """Get the current plan for a session."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetPlanQuery) -> QueryResult:
        try:
            session = await self._state_repo.load_session(query.session_id)
            if session is None:
                return QueryResult.not_found("Session")

            plan = session.get_last_plan()
            if plan is None:
                return QueryResult.ok({
                    "session_id": query.session_id,
                    "plan": None,
                    "has_plan": False,
                })

            steps_data = []
            for step in plan.steps:
                if query.include_completed_steps or not step.is_done():
                    steps_data.append({
                        "id": step.id,
                        "description": step.description,
                        "status": step.status.value
                        if hasattr(step.status, "value")
                        else str(step.status),
                    })

            return QueryResult.ok({
                "session_id": query.session_id,
                "plan": {
                    "id": plan.id,
                    "prompt": plan.prompt,
                    "steps": steps_data,
                    "total_steps": len(plan.steps),
                },
                "has_plan": True,
            })
        except Exception as exc:
            return QueryResult.fail(str(exc))


class SearchSessionsHandler(QueryHandler):
    """Search sessions by content (event text, context values)."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: SearchSessionsQuery) -> QueryResult:
        try:
            sessions = await self._state_repo.list_sessions(
                user_id=query.user_id,
            )

            query_lower = query.query.lower()
            matched = []
            for s in sessions:
                context_match = any(
                    query_lower in str(v).lower()
                    for v in s.context.values()
                ) if s.context else False

                event_match = False
                for e in s.events:
                    text = getattr(e, "message", None) or getattr(e, "text", None) or ""
                    if query_lower in text.lower():
                        event_match = True
                        break

                if context_match or event_match:
                    matched.append({
                        "id": s.id,
                        "status": s.status.value
                        if hasattr(s.status, "value")
                        else str(s.status),
                    })
                    if len(matched) >= query.limit:
                        break

            return QueryResult.ok({
                "query": query.query,
                "results": matched,
                "total": len(matched),
            })
        except Exception as exc:
            return QueryResult.fail(str(exc))


class GetSimilarSessionsHandler(QueryHandler):
    """Find sessions similar to a given session (heuristic matching)."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetSimilarSessionsQuery) -> QueryResult:
        try:
            target = await self._state_repo.load_session(query.session_id)
            if target is None:
                return QueryResult.not_found("Session")

            all_sessions = await self._state_repo.list_sessions()

            target_event_types = {type(e).__name__ for e in target.events}
            scored = []
            for s in all_sessions:
                if s.id == query.session_id:
                    continue
                score = 0.0
                s_types = {type(e).__name__ for e in s.events}
                overlap = target_event_types & s_types
                if overlap:
                    score = len(overlap) / max(len(target_event_types), 1)
                if s.status == target.status:
                    score += 0.3
                if score > 0:
                    scored.append((score, s.id))

            scored.sort(key=lambda x: -x[0])
            results = [
                {"session_id": sid, "similarity": round(s, 3)}
                for s, sid in scored[:query.limit]
            ]

            return QueryResult.ok({
                "session_id": query.session_id,
                "similar_sessions": results,
                "total": len(results),
            })
        except Exception as exc:
            return QueryResult.fail(str(exc))


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


class GetPlanVisualizationHandler(QueryHandler):
    """Return plan DAG data for visualization."""

    def __init__(self, state_repo: StateRepositoryPort):
        self._state_repo = state_repo

    async def handle(self, query: GetPlanVisualizationQuery) -> QueryResult:
        try:
            session = await self._state_repo.load_session(query.session_id)
            if session is None:
                return QueryResult.not_found("Session")

            plan = session.get_last_plan() if hasattr(session, "get_last_plan") else None
            if plan is None:
                return QueryResult.ok({"session_id": query.session_id, "plan": None})

            nodes = []
            edges = []
            for i, step in enumerate(plan.steps):
                sid = step.id or f"step_{i}"
                nodes.append({
                    "id": sid,
                    "label": (step.description or sid)[:60],
                    "status": step.status.value if hasattr(step.status, "value") else str(step.status),
                    "result": (step.result or "")[:200] if step.result else None,
                })
                if i > 0:
                    prev_id = plan.steps[i - 1].id or f"step_{i - 1}"
                    edges.append({"from": prev_id, "to": sid})

            return QueryResult.ok({
                "session_id": query.session_id,
                "plan": {
                    "status": plan.status.value if hasattr(plan.status, "value") else str(plan.status),
                    "nodes": nodes,
                    "edges": edges,
                },
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
