"""A plan update that produced no revision must not look like progress.

Two opposite defects in `UpdatingState`, four lines apart.

D21 — when `UpdatePlanCommand` fails, the state yielded an ErrorEvent and went
back to `ExecutingState` with the plan untouched. `Plan.get_next_step()` skips
only COMPLETED and FAILED steps, so a step left RUNNING (executing.py:438 and
:461 both transition here after marking it RUNNING), UNVERIFIED (:705) or
PENDING was handed straight back. The flow re-ran it, failed the update again,
and spun until `_max_step_repetitions` (3) tripped — paying for a plan-update
model call each pass. Measured: RUNNING and PENDING were re-selected; FAILED
was not, so the recorded claim that it re-selects "the same failing step" was
right about the loop and wrong about which status causes it.

D72 — on the no-mediator path, `elif isinstance(event, ErrorEvent)` set
`update_success = True`. A planner that yielded nothing but an ErrorEvent left
the failing step COMPLETED with result "Handled by plan update" and the plan
byte-identical. A failed update was laundered into a completed step, and every
downstream verification took it at face value. That path is reachable:
`factories.py` and `cli/agent_runner.py` all default `mediator=None`.
"""

from __future__ import annotations

import types
import warnings

import pytest

from weebot.application.flows.states.executing import ExecutingState
from weebot.application.flows.states.updating import UpdatingState
from weebot.domain.models.event import ErrorEvent
from weebot.domain.models.plan import Plan, Step, StepStatus


class _Result:
    def __init__(self, success: bool):
        self.success = success
        self.error = "planner unavailable"
        self.data: dict = {}


class _FailingMediator:
    async def send(self, cmd):
        return _Result(False)


class _ErroringPlanner:
    async def update_plan(self, plan, step, failure_context=""):
        yield ErrorEvent(error="planner could not produce a revised plan")


class _Ctx:
    """The slice of PlanActFlow that UpdatingState actually touches."""

    def __init__(self, plan: Plan, *, mediator=None, planner=None):
        self._plan = plan
        self._mediator = mediator
        self._planner = planner
        self._session = types.SimpleNamespace(id="s1")
        self._model = None
        self._llm = None
        self._plan_critic = None
        self._hooks = None
        self._tools: list = []
        self._plan_history = types.SimpleNamespace(get_all=lambda: [])
        self.state = None

    def set_state(self, s):
        self.state = s

    async def _emit(self, e):
        pass

    def _snapshot_plan(self):
        pass


def _plan(status: StepStatus, result: str | None = None) -> Plan:
    return Plan(
        title="t",
        steps=[
            Step(id="s1", description="the step that failed", status=status, result=result),
            Step(id="s2", description="the step after it"),
        ],
    )


async def _drive(ctx) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        async for _ in UpdatingState().execute(ctx, "task"):
            pass


@pytest.mark.parametrize(
    "status", [StepStatus.RUNNING, StepStatus.PENDING, StepStatus.UNVERIFIED]
)
@pytest.mark.asyncio
async def test_a_rejected_update_does_not_hand_back_the_same_step(status):
    ctx = _Ctx(_plan(status), mediator=_FailingMediator())
    await _drive(ctx)

    assert isinstance(ctx.state, ExecutingState)
    nxt = ctx._plan.get_next_step()
    assert nxt is not None and nxt.id == "s2", (
        f"a step left {status.value} was handed back to ExecutingState unchanged; "
        "the flow re-runs it and fails the update again until the repetition cap trips"
    )


@pytest.mark.asyncio
async def test_a_step_already_failed_is_left_alone(status=StepStatus.FAILED):
    """The one status that was already safe — and its result must survive."""
    ctx = _Ctx(_plan(StepStatus.FAILED, result="tool crashed"), mediator=_FailingMediator())
    await _drive(ctx)

    s1 = next(s for s in ctx._plan.steps if s.id == "s1")
    assert s1.status is StepStatus.FAILED
    assert s1.result == "tool crashed", "the original failure was overwritten"


@pytest.mark.asyncio
async def test_a_rejected_update_records_why(status=StepStatus.RUNNING):
    ctx = _Ctx(_plan(StepStatus.RUNNING), mediator=_FailingMediator())
    await _drive(ctx)

    s1 = next(s for s in ctx._plan.steps if s.id == "s1")
    assert s1.status is StepStatus.FAILED
    assert "rejected" in (s1.result or "").lower()


@pytest.mark.asyncio
async def test_a_planner_error_does_not_complete_the_step():
    """D72: the fail-open. An ErrorEvent is not a plan update."""
    ctx = _Ctx(_plan(StepStatus.RUNNING), planner=_ErroringPlanner())
    await _drive(ctx)

    s1 = next(s for s in ctx._plan.steps if s.id == "s1")
    assert s1.status is not StepStatus.COMPLETED, (
        "a planner that yielded nothing but an ErrorEvent marked the step COMPLETED "
        "with result 'Handled by plan update' — a failed update laundered into a "
        "completed step"
    )
    assert s1.status is StepStatus.FAILED
    assert ctx._plan.steps[0].description == "the step that failed", "the plan was not revised"


@pytest.mark.asyncio
async def test_a_real_revision_still_marks_the_step_handled():
    """Removing the fail-open must not break the path that genuinely succeeds."""
    revised = Plan(
        title="t",
        steps=[
            Step(id="s1", description="the step that failed", status=StepStatus.RUNNING),
            Step(id="s3", description="a new approach"),
        ],
    )

    class _RevisingPlanner:
        async def update_plan(self, plan, step, failure_context=""):
            from weebot.domain.models.event import PlanEvent
            from weebot.domain.models.plan import PlanStatus

            yield PlanEvent(plan=revised.model_dump(mode="json"), status=PlanStatus.UPDATED)

    ctx = _Ctx(_plan(StepStatus.RUNNING), planner=_RevisingPlanner())
    await _drive(ctx)

    s1 = next(s for s in ctx._plan.steps if s.id == "s1")
    assert s1.status is StepStatus.COMPLETED
    assert s1.result == "Handled by plan update"
    assert isinstance(ctx.state, ExecutingState)
