"""D4: the step evaluator is built, behind WEEBOT_STEP_EVALUATOR, and reaches the flow.

`progress_gate` read `flow._step_evaluator`, but nothing built one, so the gate never
ran. Three defects came with it: a fenced reply failed open, the prompt promised the
most recent output first and got the oldest, and a step the gate stopped was never
counted against the candidate skills it used.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from weebot.application.ports.step_evaluator_port import StepEvaluation
from weebot.application.services.step_evaluator import LLMStepEvaluator
from weebot.domain.models.plan import Plan, Step


def _llm(content: str):
    return SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(content=content)))


async def test_a_fenced_reply_is_scored_not_failed_open():
    llm = _llm('```json\n{"score": 0.1, "regression_detected": false, "reasoning": "no"}\n```')
    step = Step(id="s1", description="d")
    result = await LLMStepEvaluator(llm=llm).evaluate(step, "out", Plan(title="p", steps=[step]), [])
    assert not result.evaluator_failed
    assert result.score == 0.1 and not result.passed


async def test_previous_outputs_are_listed_newest_first():
    llm = _llm('{"score": 1.0}')
    step = Step(id="s9", description="d")
    await LLMStepEvaluator(llm=llm).evaluate(
        step, "out", Plan(title="p", steps=[step]), ["oldest", "middle", "newest"]
    )
    prompt = llm.chat.await_args.kwargs["messages"][0]["content"]
    assert prompt.index("[1] newest") < prompt.index("[3] oldest")


async def test_a_step_the_gate_stops_goes_to_updating_and_counts_as_a_failed_use():
    from weebot.application.flows.states import _step_outcome

    step = Step(id="s1", description="d")
    evaluator = SimpleNamespace(
        evaluate=AsyncMock(
            return_value=StepEvaluation(
                step_id="s1", score=0.1, passed=False, regression_detected=False, reasoning="x"
            )
        )
    )
    mediator = SimpleNamespace(send=AsyncMock())
    states = []
    ctx = SimpleNamespace(
        _step_evaluator=evaluator,
        _plan=Plan(title="p", steps=[step]),
        _mediator=mediator,
        _session=SimpleNamespace(id="sess"),
        set_state=states.append,
    )
    run = SimpleNamespace(result_text="out", skills_used=["cand"])

    assert await _step_outcome.progress_gate(ctx, step, run) is True
    assert states and states[-1].__class__.__name__ == "UpdatingState"
    command = mediator.send.await_args.args[0]
    assert command.skill_name == "cand" and command.passed is False


def test_the_evaluator_is_built_only_when_its_flag_is_on(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.application.di import Container

    container = Container()
    monkeypatch.setattr(container, "_create_llm_for_role", lambda role: MagicMock())

    monkeypatch.delenv("WEEBOT_STEP_EVALUATOR", raising=False)
    importlib.reload(flags)
    assert flags.STEP_EVALUATOR_ENABLED is False
    assert container._create_step_evaluator() is None

    monkeypatch.setenv("WEEBOT_STEP_EVALUATOR", "1")
    importlib.reload(flags)
    try:
        assert isinstance(container._create_step_evaluator(), LLMStepEvaluator)
    finally:
        monkeypatch.delenv("WEEBOT_STEP_EVALUATOR")
        importlib.reload(flags)


def test_the_main_flow_receives_the_step_evaluator():
    from weebot.application.di.keys import STEP_EVALUATOR
    from weebot.application.flows.flow_builder import build_flow
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.domain.models.session import Session

    evaluator = object()
    flow = build_flow(
        resolve=lambda key: evaluator if key == STEP_EVALUATOR else None,
        flow_type="plan_act",
        session=Session(id="s-flow", user_id="u", agent_id="a"),
        llm=MagicMock(),
        tools=ToolCollection(),
        mediator=MagicMock(),
    )
    assert flow._step_evaluator is evaluator
