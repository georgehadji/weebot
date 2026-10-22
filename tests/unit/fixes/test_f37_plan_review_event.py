"""F37: `flow run` printed the PlanReviewEvent as a raw repr with session_id=''.

`PlanReviewState` yielded the event without `_emit`, so it was never stamped,
saved or published, and the CLI formatter had no case for it and fell back to
`str(event)`. Seen in the real run of 2026-10-22.
"""

from __future__ import annotations

from weebot.application.flows.states.plan_review import PlanReviewState
from weebot.domain.models.event import PlanReviewEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session
from weebot.interfaces.cli.event_logger import _format_event

_PLAN = Plan(title="t", steps=[Step(id="s1", description="a"), Step(id="s2", description="b")])


class _Flow:
    def __init__(self) -> None:
        self._plan = _PLAN
        self._session = Session(id="sess-1")
        self._state_repo = None
        self.emitted: list = []

    async def _emit(self, event) -> None:
        self.emitted.append(event)
        self._session = self._session.add_event(event)

    def set_state(self, state) -> None:
        pass


async def test_plan_review_event_is_emitted_into_the_session():
    flow = _Flow()
    events = [e async for e in PlanReviewState().execute(flow, "")]
    review = [e for e in events if isinstance(e, PlanReviewEvent)]
    assert review, "no PlanReviewEvent yielded"
    assert any(isinstance(e, PlanReviewEvent) for e in flow.emitted), "never emitted"
    assert any(isinstance(e, PlanReviewEvent) for e in flow._session.events), "not in the session"


def test_cli_renders_a_plan_review_event_as_one_line():
    line = _format_event(PlanReviewEvent(plan_data=_PLAN.model_dump(mode="json"), step_count=2))
    assert "plan_data=" not in line and "session_id=" not in line
    assert "2 steps" in line
