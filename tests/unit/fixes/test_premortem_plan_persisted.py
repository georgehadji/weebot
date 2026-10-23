"""Pre-mortem risk notes survive the plan-review resume (remaining-fix plan A8).

Same class as F36: `PremortmState` replaced `context._plan` (risk notes added
to `plan.message`) without a `PlanEvent`, and the resume after plan review
restores the plan from the last `PlanEvent`, so the notes were lost.
"""

from __future__ import annotations

from weebot.application.flows.states.premortem import PremortmState
from weebot.application.services.premortem_analyzer import PremortmAnalyzer
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step
from weebot.domain.models.session import Session

_PLAN = Plan(title="t", steps=[Step(id=f"s{i}", description=f"d{i}") for i in range(3)])


class _Flow:
    def __init__(self) -> None:
        self._plan = _PLAN
        self._llm = object()
        self._session = Session(id="s1").add_event(
            PlanEvent(status=PlanStatus.CREATED, plan=_PLAN.model_dump(mode="json"))
        )

    async def _emit(self, event) -> None:
        self._session = self._session.add_event(event)

    def set_state(self, state) -> None:
        pass


async def test_risk_notes_are_in_the_plan_the_resume_restores(monkeypatch):
    async def _risks(self, plan, task):
        return ["the disk may be full"]

    monkeypatch.setattr(PremortmAnalyzer, "analyze", _risks)
    flow = _Flow()
    _ = [e async for e in PremortmState().execute(flow, "do the task")]
    assert "the disk may be full" in (flow._plan.message or "")
    restored = flow._session.get_last_plan()
    assert "the disk may be full" in (restored.message or "")
