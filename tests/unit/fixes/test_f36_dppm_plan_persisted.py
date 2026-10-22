"""F36: with DPPM planning, the plan the user approved was not the plan that ran.

`PlanningState` replaced `context._plan` with the DPPM merge but emitted no
`PlanEvent`. The resume after plan review restores the plan from the last
`PlanEvent` (`Session.get_last_plan`), so it ran the first, pre-DPPM plan.
Seen in a real CLI run on 2026-10-22: 8 steps reviewed, 3 other steps ran.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.agents.parallel_planner import ParallelPlanner
from weebot.application.flows.states.planning import PlanningState
from weebot.application.services.plan_merger import PlanMerger
from weebot.domain.models.event import PlanEvent
from weebot.domain.models.plan import Plan, PlanStatus, Step
from weebot.domain.models.session import Session

_FIRST = Plan(title="first", steps=[Step(id="step-1", description="original")])
_DPPM = Plan(
    title="DPPM plan (variant 1)",
    steps=[Step(id="dppm-1", description="merged a"), Step(id="dppm-2", description="merged b")],
)


class _Mediator:
    async def send(self, _command):
        event = PlanEvent(status=PlanStatus.CREATED, plan=_FIRST.model_dump(mode="json"))
        return SimpleNamespace(success=True, error=None, data={"events": [event.model_dump()]})


class _Flow:
    """The PlanActFlow surface PlanningState touches; `_emit` records like the publisher."""

    def __init__(self) -> None:
        session = Session(id="s1")
        extra = {**session.context.extra, "_intent_reviewed": True}
        self._session = session.model_copy(
            update={"context": session.context.model_copy(update={"extra": extra})}
        )
        self._mediator = _Mediator()
        self._llm = object()
        self._model = None
        self._planning_mode = "dppm"
        self._plan = None
        self._plan_critic = None
        self._event_bus = None
        self._skill_prompt = ""
        self.next_state = None

    def _maybe_switch_model_for_context(self):
        return None

    async def _emit(self, event) -> None:
        self._session = self._session.add_event(event)

    def _snapshot_plan(self) -> None:
        pass

    def _get_awm(self):
        return None

    def set_state(self, state) -> None:
        self.next_state = state


@pytest.fixture(autouse=True)
def _dppm_returns_a_different_plan(monkeypatch):
    async def _generate(self, prompt, num_alternatives=2):
        return ["candidate-1", "candidate-2"]

    async def _merge(self, candidates, original_prompt):
        return _DPPM

    monkeypatch.setattr(ParallelPlanner, "generate", _generate)
    monkeypatch.setattr(PlanMerger, "merge", _merge)


async def _plan(flow: _Flow) -> list:
    return [event async for event in PlanningState().execute(flow, "do three tool calls")]


async def test_resume_restores_the_dppm_plan_the_user_reviews():
    flow = _Flow()
    await _plan(flow)
    assert [s.id for s in flow._plan.steps] == ["dppm-1", "dppm-2"]
    restored = flow._session.get_last_plan()
    assert [s.id for s in restored.steps] == ["dppm-1", "dppm-2"]


async def test_dppm_plan_is_yielded_so_clients_show_it():
    events = await _plan(_Flow())
    plans = [e for e in events if isinstance(e, PlanEvent)]
    assert plans[-1].status == PlanStatus.UPDATED
    assert plans[-1].plan["title"] == "DPPM plan (variant 1)"
