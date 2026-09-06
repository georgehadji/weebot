"""A degraded result must not look like a real one.

Two verification paths fail open by documented policy, and W2 escalated whether
that policy is right as a product decision rather than a defect. This module
does not touch the policy. It closes the separate defect underneath it: when the
instrument fails, the value it produces is byte-identical to a real answer, so
nothing downstream -- including the person reading the logs -- can tell that no
verification happened.

  * `LLMStepEvaluator.evaluate` returns `score=1.0, passed=True` on any
    exception. 1.0 is the maximum, indistinguishable from a step judged
    perfect. The live consumer, `executing.py`, only logs when `passed` is
    False, so an evaluator outage is completely silent at the call site.
  * `TrajectoryBuilder` records `failure_modes=[]` when the analyst LLM fails.
    An empty list is stored in SQLite and read back as "analysed, no failure
    modes found" -- the analysis dataset is quietly diluted with rows that
    were never analysed.

Marking the degradation changes no pass/fail outcome. It makes the failure
legible, which is what the policy decision will need either way.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from weebot.application.ports.step_evaluator_port import StepEvaluation


class _ExplodingLLM:
    """An LLM port whose every call fails, the way an outage looks."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or RuntimeError("upstream 503")

    async def chat(self, *a, **k):
        raise self.exc


class _EmptyLLM:
    """An LLM that answers, with nothing in it."""

    async def chat(self, *a, **k):
        return type("R", (), {"content": ""})()


def _step():
    from weebot.domain.models.plan import Step

    return Step(id="s1", description="do the thing")


def _session():
    from weebot.domain.models.session import Session

    return Session(id="sess1", user_id="u", agent_id="a")


def _scored():
    from weebot.domain.models.event import TrajectoryScored

    return TrajectoryScored(
        session_id="sess1",
        task_id="t1",
        score=0.5,
        failure_modes=[],
        success_patterns=[],
        trajectory_summary="fallback summary",
    )


def _plan():
    from weebot.domain.models.plan import Plan, Step

    return Plan(title="goal", steps=[Step(id="s1", description="do the thing")])


# --------------------------------------------------------------------------
# D13 -- the evaluator
# --------------------------------------------------------------------------

def test_the_evaluation_model_can_express_that_it_failed():
    names = {f.name for f in fields(StepEvaluation)}
    assert "evaluator_failed" in names, (
        "StepEvaluation has no way to say the evaluator did not run; a caller "
        f"sees only {sorted(names)}"
    )


@pytest.mark.asyncio
async def test_an_evaluator_outage_is_marked_not_disguised():
    from weebot.application.services.step_evaluator import LLMStepEvaluator

    ev = await LLMStepEvaluator(_ExplodingLLM()).evaluate(
        step=_step(), output="whatever", plan=_plan(), previous_outputs=[]
    )
    assert ev.evaluator_failed is True, "a total outage is reported as a real verdict"


@pytest.mark.asyncio
async def test_an_empty_completion_is_marked_too():
    from weebot.application.services.step_evaluator import LLMStepEvaluator

    ev = await LLMStepEvaluator(_EmptyLLM()).evaluate(
        step=_step(), output="whatever", plan=_plan(), previous_outputs=[]
    )
    assert ev.evaluator_failed is True, "an empty completion is reported as a real verdict"


def test_the_flow_warns_when_no_evaluation_happened():
    """The live consumer only logged on `not passed`, so an outage was silent.

    Asserted against the source of `executing.py` rather than by driving a whole
    flow: the branch is one `elif` inside a 700-line state handler whose setup
    would dwarf what is being checked, and the property -- that the call site
    reacts to `evaluator_failed` at all -- is visible statically.
    """
    import inspect

    from weebot.application.flows.states import executing

    src = inspect.getsource(executing)
    assert "evaluator_failed" in src, (
        "the live consumer of StepEvaluation never looks at evaluator_failed, so "
        "an evaluator outage is still silent at the call site"
    )


# --------------------------------------------------------------------------
# D16 -- the trajectory analyst
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_unanalysed_trajectory_is_not_recorded_as_clean():
    from weebot.application.services.trajectory_builder import TrajectoryBuilder

    summary = await TrajectoryBuilder(_ExplodingLLM()).build(_session(), _scored())
    assert summary.failure_modes != [], (
        "a failed analysis is persisted with an empty failure_modes list. The "
        "analyst prompt defines that as 'the task succeeded fully', so a row "
        "nothing analysed is stored as a clean run."
    )
    assert any("unavailable" in m for m in summary.failure_modes), (
        f"the marker does not say why: {summary.failure_modes}"
    )


# --------------------------------------------------------------------------
# Controls -- must pass before and after
# --------------------------------------------------------------------------

def test_a_normal_evaluation_is_not_marked_as_failed():
    ev = StepEvaluation(
        step_id="s1", score=0.9, passed=True, regression_detected=False, reasoning="fine"
    )
    assert getattr(ev, "evaluator_failed", False) is False


@pytest.mark.asyncio
async def test_the_fail_open_policy_is_unchanged():
    """This module must not decide the escalated product question."""
    from weebot.application.services.step_evaluator import LLMStepEvaluator

    ev = await LLMStepEvaluator(_ExplodingLLM()).evaluate(
        step=_step(), output="whatever", plan=_plan(), previous_outputs=[]
    )
    assert ev.passed is True, "the fail-open policy was changed; that is not this fix's call"


@pytest.mark.asyncio
async def test_a_successful_analysis_still_reports_its_own_failure_modes():
    from weebot.application.services.trajectory_builder import TrajectoryBuilder

    class _GoodLLM:
        async def chat(self, *a, **k):
            return type("R", (), {"content": '{"trajectory_text": "t", '
                                             '"failure_modes": ["looped"], '
                                             '"success_patterns": ["p"]}'})()

    summary = await TrajectoryBuilder(_GoodLLM()).build(_session(), _scored())
    assert summary.failure_modes == ["looped"]
    assert summary.success_patterns == ["p"]


@pytest.mark.asyncio
async def test_a_genuinely_clean_trajectory_still_records_no_failure_modes():
    """The marker must not be confused with a real, empty analysis."""
    from weebot.application.services.trajectory_builder import TrajectoryBuilder

    class _CleanLLM:
        async def chat(self, *a, **k):
            return type("R", (), {"content": '{"trajectory_text": "t", '
                                             '"failure_modes": [], '
                                             '"success_patterns": ["p"]}'})()

    summary = await TrajectoryBuilder(_CleanLLM()).build(_session(), _scored())
    assert summary.failure_modes == [], f"a clean run was marked: {summary.failure_modes}"


# --------------------------------------------------------------------------
# D61 -- a parsed but wrong-shaped analysis used to escape the fail-open
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content",
    [
        "[]",                              # valid JSON, not an object
        "123",
        '"a string"',
        "null",
        '{"failure_modes": "oops"}',       # object, wrong field type
        '{"failure_modes": [1, 2]}',
        '{"failure_modes": null}',
        '{"trajectory_text": 7}',
        '{"success_patterns": {"a": 1}}',
    ],
)
@pytest.mark.asyncio
async def test_a_parsed_but_unusable_analysis_takes_the_fail_open_path(content):
    """`json.loads` succeeding is not the same as the response being usable.

    The `try` covered the chat call and the parse, so a completion that parsed
    into a list raised AttributeError from `.get`, and one that parsed into an
    object with a wrong-typed field raised ValidationError from Pydantic --
    both past the handler meant to absorb exactly this. `.get(key, default)`
    does not help: it substitutes only when the key is ABSENT, never when it is
    present and wrong.
    """
    from weebot.application.services.trajectory_builder import TrajectoryBuilder

    class _LLM:
        async def chat(self, *a, **k):
            return type("R", (), {"content": content})()

    summary = await TrajectoryBuilder(_LLM()).build(_session(), _scored())
    assert summary.failure_modes == ["analysis_unavailable"], (
        f"{content!r} escaped the fail-open instead of being marked"
    )
