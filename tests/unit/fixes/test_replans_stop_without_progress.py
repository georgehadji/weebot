"""Failed steps stop being replanned when nothing moves forward.

Found on live session de5d0990: step-1 failed, and the replanner swapped in step-1b,
1c, 1d, 1e and 1f, each one a fresh id chasing the same unexplained error, so the
per-step repetition limit never applied. Only the token budget ended it. Now three
failures in a row without a completed step stop the run instead of a fourth replan.
"""

from __future__ import annotations

from types import SimpleNamespace

from weebot.application.flows.states._step_outcome import (
    MAX_REPLANS_WITHOUT_PROGRESS,
    complete_step,
    route_failure,
)
from weebot.application.flows.states.updating import UpdatingState
from weebot.application.flows.states.verifying import VerifyingState
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.plan import Plan, Step, StepStatus

ERROR = "Trajectory semantic_loop for step 'x': Different tool calls producing identical output."


def _context(n):
    steps = [Step(id=f"s{i}", description=f"try {i}") for i in range(n)]
    ctx = SimpleNamespace(_plan=Plan(title="t", steps=steps), states=[])
    ctx.set_state = ctx.states.append
    return ctx


def _run():
    return SimpleNamespace(events=[ErrorEvent(error=ERROR)], elapsed_s=1.0, result_text="")


async def test_the_failure_after_the_limit_stops_the_run():
    n = MAX_REPLANS_WITHOUT_PROGRESS + 1
    ctx = _context(n)
    returned = [await route_failure(ctx, ctx._plan.steps[i], _run()) for i in range(n)]

    assert all(isinstance(s, UpdatingState) for s in ctx.states[:-1])
    assert isinstance(ctx.states[-1], VerifyingState)
    assert isinstance(returned[-1], ErrorEvent) and "replanned" in returned[-1].error
    assert ctx._plan.steps[-1].status == StepStatus.FAILED


async def test_a_completed_step_resets_the_count():
    n = MAX_REPLANS_WITHOUT_PROGRESS + 1
    ctx = _context(n + 1)
    for i in range(n - 1):
        await route_failure(ctx, ctx._plan.steps[i], _run())
    complete_step(ctx, ctx._plan.steps[n - 1], SimpleNamespace(result_text="ok", elapsed_s=1.0))
    assert await route_failure(ctx, ctx._plan.steps[n], _run()) is None
    assert isinstance(ctx.states[-1], UpdatingState)
