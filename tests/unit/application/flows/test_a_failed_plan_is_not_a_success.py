"""P3 — a plan where nothing worked reported success, and was learned from.

`Step.is_done()` is `COMPLETED or FAILED`. That is correct for its main
caller, `Plan.get_next_step()`, which needs to know what is still *runnable*.
Three other places read it as "succeeded":

    Plan.is_complete()          all(is_done())  ->  True when every step FAILED
    CompletedState              stamps PlanStatus.COMPLETED unconditionally
    CompletedState              success_score from is_done()  ->  1.0

Measured before the fix:

    every step FAILED    is_complete=True   template success_score=1.0
    1 done, 1 failed     is_complete=True   template success_score=1.0
    all completed        is_complete=True   template success_score=1.0

The score is the sharp end. A plan in which nothing succeeded was written to
the plan-template cache with a **perfect** score, so the failure was not
merely reported as a success -- it was learned from as one and would be
preferentially retrieved for the next similar task.

`PlanStatus` has no failure member at all (created/updated/running/completed),
so the plan object cannot express this. `SessionStatus` can, and both the API
and the web UI already understand `failed`, so that is the lever used here.
Giving `PlanStatus` a FAILED member is a domain change that crosses into the
TypeScript types and is left as a recorded gap.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.plan import Plan, Step, StepStatus


def _plan(*statuses: StepStatus) -> Plan:
    return Plan(
        goal="g",
        steps=[Step(id=f"s{i}", description=f"s{i}", status=st) for i, st in enumerate(statuses)],
    )


def test_is_complete_still_means_nothing_is_runnable():
    """The predicate that was there is kept, and kept honest.

    REGRESSION GUARD: `get_next_step()` depends on FAILED counting as done, or
    a failed step would be retried forever. Changing `is_done()` was the
    tempting fix and would have caused exactly that.
    """
    assert _plan(StepStatus.FAILED).is_complete() is True
    assert _plan(StepStatus.FAILED).get_next_step() is None
    assert _plan(StepStatus.RUNNING).is_complete() is False
    assert _plan(StepStatus.RUNNING).get_next_step() is not None


def test_is_successful_separates_finished_from_worked():
    """The predicate that was missing."""
    assert _plan(StepStatus.COMPLETED, StepStatus.COMPLETED).is_successful() is True
    assert _plan(StepStatus.COMPLETED, StepStatus.FAILED).is_successful() is False
    assert _plan(StepStatus.FAILED, StepStatus.FAILED).is_successful() is False
    assert _plan(StepStatus.COMPLETED, StepStatus.RUNNING).is_successful() is False
    # An empty plan has not succeeded at anything, matching `is_complete()`.
    assert Plan(goal="g", steps=[]).is_successful() is False


def test_failed_steps_names_them():
    failed = _plan(StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.FAILED).failed_steps()
    assert [s.id for s in failed] == ["s1", "s2"]
    assert _plan(StepStatus.COMPLETED).failed_steps() == []


def test_a_wholly_failed_plan_does_not_score_1_0_as_a_template():
    """The defect in one number: a template for a plan that failed, scored 1.0."""
    plan = _plan(StepStatus.FAILED, StepStatus.FAILED)

    old_score = round(sum(1 for s in plan.steps if s.is_done()) / len(plan.steps), 2)
    new_score = round(
        sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED) / len(plan.steps), 2
    )

    assert old_score == 1.0, "the premise: is_done() scored total failure as perfect"
    assert new_score == 0.0
    assert plan.is_complete() is True, "and it terminated, which is why it got that far"
    assert plan.is_successful() is False


@pytest.mark.asyncio
async def test_the_session_ends_failed_when_a_step_failed(monkeypatch):
    """`CompletedState` set SessionStatus.COMPLETED unconditionally.

    Driven through the real state object, because the defect lives in the
    transition, not in the predicate.
    """
    import asyncio

    from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
    from weebot.application.flows.states.completed import CompletedState
    from weebot.application.services import background_tasks as _bg

    # `CompletedState` starts three background jobs at the end — retention
    # review, skill-gap processing and a dream scan — each of which builds a
    # `Container()` and, through it, live LLM adapters. None is under test, and
    # the dream scan blocks here. Suppressed explicitly so the test says what it
    # is not exercising.
    #
    # This used to monkeypatch `asyncio.ensure_future` itself, because the three
    # jobs were spawned with no owner to reach for (P3-4). They now go through
    # `BackgroundTasks`, so the suppression can name exactly what it suppresses.
    spawned: list = []

    def _record_instead_of_running(self, coro, *, name=""):
        spawned.append(name)
        coro.close()
        return None

    monkeypatch.setattr(_bg.BackgroundTasks, "spawn", _record_instead_of_running)
    from weebot.domain.models.session import Session, SessionStatus
    from weebot.application.models.tool_collection import ToolCollection

    async def _drive(plan: Plan):
        # A REAL flow, not a SimpleNamespace. A hand-built stand-in silently
        # diverges from the object under test — earlier in this programme one
        # took a fallback branch and reproduced, inside the test, the very
        # mistake the test was written to catch.
        flow = PlanActFlow(
            PlanActFlowConfig(
                llm=_DummyLLM(),
                tools=ToolCollection(),
                session=Session(id="sess-1", task="t"),
                max_iterations=1,
            )
        )
        flow._plan = plan
        # AWM workflow induction and trajectory scoring both fire from
        # CompletedState when an LLM and a mediator are present, and both make
        # real calls. Neither is under test here; the terminal session status
        # is. Disabling them keeps the flow real and the test hermetic.
        flow._llm = None
        flow._mediator = None
        async for _ in CompletedState().execute(flow, "t"):
            pass
        return flow._session.status

    assert await _drive(_plan(StepStatus.COMPLETED)) == SessionStatus.COMPLETED
    assert await _drive(_plan(StepStatus.FAILED)) == SessionStatus.FAILED
    assert await _drive(_plan(StepStatus.COMPLETED, StepStatus.FAILED)) == SessionStatus.FAILED


@pytest.mark.asyncio
async def test_the_plan_itself_records_that_it_failed(monkeypatch):
    """`PlanStatus` had no failure member, so the plan object could not say it.

    `CompletedState` stamped COMPLETED unconditionally — not carelessness, the
    enum offered nothing else. Fixed backend-only by decision:
    `weebot-ui/src/types/events.ts` keeps its stale union (it already omits
    `running`), so the UI sees `failed` as an unknown value and
    `SessionStatus.FAILED`, which both stacks understand, carries the
    user-facing outcome. That gap is recorded, not overlooked.
    """
    import asyncio

    from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
    from weebot.application.flows.states.completed import CompletedState
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.application.services import background_tasks as _bg
    from weebot.domain.models.plan import PlanStatus
    from weebot.domain.models.session import Session

    monkeypatch.setattr(
        _bg.BackgroundTasks, "spawn", lambda self, coro, *, name="": coro.close()
    )

    async def _stamp(plan: Plan) -> tuple[PlanStatus, PlanStatus]:
        flow = PlanActFlow(
            PlanActFlowConfig(
                llm=_DummyLLM(),
                tools=ToolCollection(),
                session=Session(id="sess-stamp", task="t"),
                max_iterations=1,
            )
        )
        flow._plan = plan
        flow._llm = None
        flow._mediator = None
        emitted: list = []
        async for event in CompletedState().execute(flow, "t"):
            status = getattr(event, "status", None)
            if isinstance(status, PlanStatus):
                emitted.append(status)
        return flow._plan.status, emitted[0]

    stamped, event_status = await _stamp(_plan(StepStatus.FAILED, StepStatus.FAILED))
    assert stamped == PlanStatus.FAILED, "a wholly failed plan still stamped itself completed"
    assert event_status == PlanStatus.FAILED, "the PlanEvent told consumers it succeeded"

    stamped, event_status = await _stamp(_plan(StepStatus.COMPLETED, StepStatus.FAILED))
    assert stamped == PlanStatus.FAILED, "one failed step is still not a success"

    stamped, event_status = await _stamp(_plan(StepStatus.COMPLETED))
    assert stamped == PlanStatus.COMPLETED
    assert event_status == PlanStatus.COMPLETED


class _DummyLLM:
    """The flow requires an LLMPort; nothing here calls it."""

    async def chat(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("CompletedState must not call the LLM in these tests")


@pytest.mark.asyncio
async def test_mid_execution_steering_reaches_the_step():
    """P3-2 — steering was polled, logged, formatted, and then not sent.

        effective_prompt = prompt
        if steering_msg:
            logger.info("Steering received for session %s: %s", ...)
            effective_prompt = f"{prompt}\\n\\n[STEERING — ...]"
        ...
            user_input=prompt,          # <- the ORIGINAL

    `effective_prompt` was assigned twice and read nowhere. A user correcting
    an agent mid-run got a log line saying they were heard and no change in
    behaviour — a fail-open control that logs success.

    Asserted against the command the mediator actually receives, because the
    defect is precisely that the local and the argument had drifted apart.
    """
    from weebot.application.flows.states.executing import ExecutingState

    sent: list = []

    class _Steering:
        async def poll(self, _session_id):
            return "stop using tabs, use spaces"

    class _Mediator:
        async def send(self, command):
            sent.append(command)
            raise _Stop()

    class _Stop(Exception):
        pass

    from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

    flow = PlanActFlow(
        PlanActFlowConfig(
            llm=_DummyLLM(),
            tools=ToolCollection(),
            session=Session(id="sess-steer", task="write the parser"),
            max_iterations=1,
        )
    )
    flow._plan = _plan(StepStatus.PENDING)
    flow._steering = _Steering()
    flow._mediator = _Mediator()

    with pytest.raises(_Stop):
        async for _ in ExecutingState().execute(flow, "write the parser"):
            pass

    assert sent, "the step command was never built"
    user_input = getattr(sent[0], "user_input", "")
    assert "stop using tabs" in user_input, (
        "the steering message did not reach the step; the original prompt was sent"
    )
    assert "write the parser" in user_input, "the original task must survive too"
