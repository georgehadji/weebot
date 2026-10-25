"""A session that has not planned yet must still answer with the shape the UI reads.

Seen live: the Plan tab threw "Cannot read properties of undefined (reading 'map')" because the
no-plan answer had no `nodes`.
"""

from __future__ import annotations

from weebot.application.cqrs.handlers.plan_queries import GetPlanVisualizationHandler
from weebot.application.cqrs.queries import GetPlanVisualizationQuery
from weebot.domain.models.session import Session


class _Repo:
    async def load_session(self, session_id):
        return Session(id=session_id, user_id="u", agent_id="a")


async def test_no_plan_answers_with_empty_nodes_and_edges():
    result = await GetPlanVisualizationHandler(_Repo()).handle(
        GetPlanVisualizationQuery(session_id="s")
    )
    assert result.success
    assert result.data["nodes"] == [] and result.data["edges"] == []
    assert result.data["plan"] is None
