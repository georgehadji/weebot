"""Query handlers for session, plan, and meta queries.

Split from query_handlers.py during architecture remediation.
"""
from __future__ import annotations

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.application.services.task_runner import TaskRunner
from weebot.application.models.tool_collection import ToolCollection

from weebot.application.cqrs.queries import (
    GetPlanQuery,
    GetPlanVisualizationQuery,
)

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

