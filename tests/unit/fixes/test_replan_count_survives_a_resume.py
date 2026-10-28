"""The count of replans without progress survives a pause and resume.

Found by review of the replan cap: the counter lived on the flow object, and a resume
(plan approval after a full replan, a budget grant) builds a new flow with the counter
at 0, so with plan review on the cap of three was never reached. The count now lives in
the session, which the resumed flow loads.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.flows.states._step_outcome import (
    MAX_REPLANS_WITHOUT_PROGRESS,
    route_failure,
)
from weebot.application.flows.states.verifying import VerifyingState
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session

ERROR = "Trajectory semantic_loop for step 'x': Different tool calls producing identical output."


def _steps(n):
    return [Step(id=f"s{i}", description=f"try {i}") for i in range(n)]


def _flow(session, steps):
    ctx = SimpleNamespace(_plan=Plan(title="t", steps=steps), _session=session, states=[])
    ctx.set_state = ctx.states.append
    return ctx


def _run():
    return SimpleNamespace(events=[ErrorEvent(error=ERROR)], elapsed_s=1.0, result_text="")


async def test_a_new_flow_on_the_same_session_keeps_counting():
    steps = _steps(MAX_REPLANS_WITHOUT_PROGRESS + 1)
    session = Session(id="s")
    for step in steps[:-1]:
        flow = _flow(session, steps)  # a fresh flow per failure, as after each resume
        await route_failure(flow, step, _run())
        session = flow._session

    last = _flow(session, steps)
    assert isinstance(await route_failure(last, steps[-1], _run()), ErrorEvent)
    assert isinstance(last.states[-1], VerifyingState)


async def test_the_stop_clears_the_count_for_the_next_run():
    steps = _steps(MAX_REPLANS_WITHOUT_PROGRESS + 2)
    flow = _flow(Session(id="s"), steps)
    for step in steps[:-1]:
        await route_failure(flow, step, _run())
    assert await route_failure(flow, steps[-1], _run()) is None
