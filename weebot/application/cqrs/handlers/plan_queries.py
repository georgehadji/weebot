"""Query handler for plan visualization.

Scope note (2026-08-04 pre-existing-architecture-debt audit, RC-1):
``GetPlanHandler`` previously lived here but had no dispatch site
anywhere in the codebase; it was removed along with GetPlanQuery.
``GetPlanVisualizationHandler`` is live — dispatched by
``interfaces/web/routers/ops_router.py``'s plan-viz endpoint.
"""

from __future__ import annotations

from weebot.application.cqrs.base import QueryHandler, QueryResult
from weebot.application.ports.state_repo_port import StateRepositoryPort

from weebot.application.cqrs.queries import GetPlanVisualizationQuery


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
                nodes.append(
                    {
                        "id": sid,
                        "label": (step.description or sid)[:60],
                        "status": (
                            step.status.value if hasattr(step.status, "value") else str(step.status)
                        ),
                        "result": (step.result or "")[:200] if step.result else None,
                    }
                )
                if i > 0:
                    prev_id = plan.steps[i - 1].id or f"step_{i - 1}"
                    edges.append({"from": prev_id, "to": sid})

            return QueryResult.ok(
                {
                    "session_id": query.session_id,
                    "plan": {
                        "status": (
                            plan.status.value if hasattr(plan.status, "value") else str(plan.status)
                        ),
                        "nodes": nodes,
                        "edges": edges,
                    },
                }
            )
        except Exception as exc:
            return QueryResult.fail(str(exc))
