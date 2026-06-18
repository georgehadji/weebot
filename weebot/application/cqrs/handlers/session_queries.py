"""Query handlers for session, plan, and meta queries.

Split from query_handlers.py during architecture remediation.
"""
from __future__ import annotations

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.application.models.tool_collection import ToolCollection

from weebot.application.cqrs.queries import (
    GetSessionQuery,
    ListSessionsQuery,
    GetSessionStatusQuery,
    GetSessionHistoryQuery,
    SearchSessionsQuery,
    GetSimilarSessionsQuery,
)

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

