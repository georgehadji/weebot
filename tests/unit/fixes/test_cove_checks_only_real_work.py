"""CoVe verifies the steps that did work, not steps a replan stood in for.

Found on live session de5d0990: every step failed and was marked COMPLETED with the
result "Handled by plan update", so VerifyingState took them for finished work and
paid for three question-and-answer calls that could only answer UNKNOWN.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.flows.states.completed import CompletedState
from weebot.application.flows.states.verifying import VerifyingState
from weebot.domain.models.plan import REPLACED_BY_PLAN_UPDATE as HANDLED_BY_PLAN_UPDATE
from weebot.domain.models.plan import Plan, Step, StepStatus


def _flow(steps):
    flow = SimpleNamespace(_plan=Plan(title="t", steps=steps), states=[])
    flow.set_state = flow.states.append
    return flow


def _step(i, result):
    return Step(id=f"s{i}", description=f"do {i}", status=StepStatus.COMPLETED, result=result)


async def _verify(flow, monkeypatch):
    asked = []

    async def questions(self, _flow, summary, n):
        asked.append(summary)
        return []

    monkeypatch.setattr(VerifyingState, "_generate_questions", questions)
    events = [e async for e in VerifyingState().execute(flow)]
    return events, asked


async def test_a_run_where_only_replans_finished_is_not_verified(monkeypatch):
    flow = _flow([_step(1, HANDLED_BY_PLAN_UPDATE), _step(2, HANDLED_BY_PLAN_UPDATE)])
    events, asked = await _verify(flow, monkeypatch)
    assert asked == [] and events == []
    assert isinstance(flow.states[-1], CompletedState)


async def test_only_real_results_are_checked(monkeypatch):
    flow = _flow([_step(1, HANDLED_BY_PLAN_UPDATE), _step(2, "moved 12 files")])
    _, asked = await _verify(flow, monkeypatch)
    assert "moved 12 files" in asked[0] and HANDLED_BY_PLAN_UPDATE not in asked[0]
