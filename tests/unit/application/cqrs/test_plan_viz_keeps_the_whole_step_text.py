"""The plan view must get each step's whole description.

`GetPlanVisualizationHandler` cut every node label to 60 characters, so the Plan tab showed
"Create the output directory Output/lyapunov-hamiltonian-brie" and no layout could show the rest.
"""

from __future__ import annotations

from weebot.application.cqrs.handlers.plan_queries import GetPlanVisualizationHandler
from weebot.application.cqrs.queries import GetPlanVisualizationQuery
from weebot.domain.models.event import PlanEvent, PlanStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session

LONG = (
    "Create the output directory Output/lyapunov-hamiltonian-brief/ and a notes file "
    "to collect raw findings, with one section per source bucket"
)


class _Repo:
    def __init__(self, plan: Plan):
        self._session = Session(id="s", user_id="u", agent_id="a").add_event(
            PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump())
        )

    async def load_session(self, session_id):
        return self._session


async def test_a_long_description_is_not_cut():
    plan = Plan(title="p", message="m", steps=[Step(id="s1", description=LONG)])
    result = await GetPlanVisualizationHandler(_Repo(plan)).handle(
        GetPlanVisualizationQuery(session_id="s")
    )
    assert result.success
    assert [n["label"] for n in result.data["plan"]["nodes"]] == [LONG]
    assert len(LONG) > 60


async def test_a_step_without_a_description_is_labelled_by_its_id():
    plan = Plan(title="p", message="m", steps=[Step(id="s1", description="")])
    result = await GetPlanVisualizationHandler(_Repo(plan)).handle(
        GetPlanVisualizationQuery(session_id="s")
    )
    assert [n["label"] for n in result.data["plan"]["nodes"]] == ["s1"]
