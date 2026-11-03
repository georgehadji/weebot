"""Loop detectors: cycles, duplicate-result stubs, empty replies, repetition, wrap-up (H11)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from weebot.application.agents.executor._iteration_guard import IterationGuard
from weebot.application.agents.executor._loop_detectors import (
    CycleDetector,
    DuplicateResultStub,
    EmptyResponseBudget,
    GuardConfig,
    RepetitionGuard,
    Verdict,
    WallClockWrapUp,
)
from weebot.application.agents.executor._tool_batch import ToolBatchRunner
from weebot.application.agents.executor._turn import TurnOutcome, retry_empty_turn
from weebot.domain.models.plan import Step
from weebot.domain.models.tool_result import ToolResult


def _kinds(detector, signatures):
    return [v.kind if (v := detector.observe(s)) else None for s in signatures]


def test_a_b_a_b_is_nudged_once_then_stopped():
    kinds = _kinds(CycleDetector((2, 3, 4)), ["A", "B", "A", "B", "A"])
    assert kinds == [None, None, None, Verdict.NUDGE, Verdict.STOP]


def test_a_b_c_a_b_c_is_a_cycle_of_three():
    kinds = _kinds(CycleDetector((2, 3, 4)), list("ABCABC"))
    assert kinds[-1] is Verdict.NUDGE


def test_progress_is_not_a_cycle_and_a_plain_repeat_is_left_to_the_signature_limit():
    assert set(_kinds(CycleDetector((2, 3, 4)), list("ABCDEFG"))) == {None}
    assert set(_kinds(CycleDetector((2, 3, 4)), ["A", "A", "A", "A"])) == {None}


def test_identical_results_become_stubs_that_name_the_first_call():
    stub = DuplicateResultStub(min_chars=10)
    text = "x" * 50
    assert stub.observe(1, text) is None
    assert stub.observe(2, "y" * 50) is None
    assert stub.observe(3, text) == "[identical to result of call #1]"
    assert stub.observe(4, "ok") is None and stub.observe(5, "ok") is None  # too short


def test_empty_replies_retry_only_while_the_wasted_cost_is_under_the_cap():
    budget = EmptyResponseBudget(max_retries=2, ratio=0.5, cap_usd=0.02)
    assert budget.observe(turn_cost=0.001, step_cost=0.10).kind is Verdict.RETRY
    assert budget.observe(turn_cost=0.001, step_cost=0.10).kind is Verdict.RETRY
    assert budget.observe(turn_cost=0.001, step_cost=0.10).kind is Verdict.STOP  # retries used

    costly = EmptyResponseBudget(max_retries=2, ratio=0.5, cap_usd=0.02)
    assert costly.observe(turn_cost=0.03, step_cost=1.0).kind is Verdict.STOP  # over $0.02

    first_turn = EmptyResponseBudget(max_retries=2, ratio=0.5, cap_usd=0.02)
    assert first_turn.observe(turn_cost=0.01, step_cost=0.01).kind is Verdict.STOP  # over half


def test_near_identical_text_is_nudged_and_different_text_is_not():
    guard = RepetitionGuard(threshold=0.85, window=2)
    said = "I will now read the configuration file and then report back what it contains"
    assert guard.observe(said) is None
    assert guard.observe(said + " today") is not None
    assert guard.observe("Completely different words appear in a brand new sentence") is None
    assert guard.observe("ok") is None  # fewer than five words: nothing to compare


def test_the_wrap_up_note_fires_once_at_the_configured_share():
    now = [0.0]
    wrap = WallClockWrapUp(budget_s=100, ratio=0.8, clock=lambda: now[0])
    now[0] = 79.0
    assert wrap.observe() is None
    now[0] = 80.0
    assert wrap.observe() is not None
    assert wrap.observe() is None


def test_the_guard_reports_a_cycle_through_record_tool_call():
    guard = IterationGuard("s", GuardConfig())
    kinds = [v.kind if (v := guard.record_tool_call(s)) else None for s in "ABAB"]
    assert kinds[-1] is Verdict.NUDGE


# ── executor integration ────────────────────────────────────────────────────


def _turn(content=""):
    return TurnOutcome(response=SimpleNamespace(tool_calls=[]), assistant_content=content)


def _executor(spend):
    meter = SimpleNamespace(spent=lambda _sid: spend[0])
    buffer = [{"role": "assistant", "content": ""}]
    return SimpleNamespace(_cost_meter=meter, _conversation_buffer=buffer)


def test_an_empty_reply_is_replaced_by_a_nudge_in_a_user_message():
    spend = [1.0]
    executor, guard = _executor(spend), IterationGuard("s")
    spend[0] = 1.001  # the empty turn cost $0.001 of a $1.001 step

    assert retry_empty_turn(executor, guard, _turn(), spent_before=1.0, step_start=0.0)
    assert [m["role"] for m in executor._conversation_buffer] == ["user"]


def test_a_non_empty_reply_and_a_reply_without_a_meter_are_left_alone():
    guard = IterationGuard("s")
    assert not retry_empty_turn(_executor([0.0]), guard, _turn("done"), 0.0, 0.0)

    executor = SimpleNamespace(_cost_meter=None, _conversation_buffer=[{"role": "assistant"}])
    assert not retry_empty_turn(executor, guard, _turn(), 0.0, 0.0)
    assert len(executor._conversation_buffer) == 1


def _batch_executor(outputs):
    results = [ToolResult(output=o) for o in outputs]
    return SimpleNamespace(
        _trajectory_monitor=None,
        _max_steps=40,
        _tools=None,
        _conversation_buffer=[],
        _middleware_chain=None,
        _spillover_store=None,
        _facts={},
        _present_tool_output=AsyncMock(side_effect=lambda name, result: result.output),
        _vision_enabled=lambda: False,
        _tool_executor=SimpleNamespace(execute_tool_batch=AsyncMock(return_value=results)),
    )


def _calls(n):
    return [
        {"id": f"c{i}", "function": {"name": f"t{i}", "arguments": f'{{"n": {i}}}'}}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_a_repeated_result_reaches_the_model_as_a_stub_and_the_ui_keeps_the_text():
    same = "same result text " * 20
    executor = _batch_executor([same, "other", same])
    outcome = await ToolBatchRunner().run(
        executor, Step(id="s", description="d"), _calls(3), IterationGuard("s"), step_result=""
    )

    contents = [m["content"] for m in executor._conversation_buffer if m["role"] == "tool"]
    assert contents[2] == "[identical to result of call #1]" and contents[0] == same
    shown = [e.result for e in outcome.events if getattr(e, "result", None)]
    assert shown.count(same) == 2  # the UI events kept the real text for both


@pytest.mark.asyncio
async def test_notes_and_a_cycle_nudge_follow_the_tool_messages():
    executor = _batch_executor(["a", "b", "c", "d"])
    calls = [
        {"id": f"c{i}", "function": {"name": "t", "arguments": f'{{"n": {i % 2}}}'}}
        for i in range(4)
    ]
    await ToolBatchRunner().run(
        executor, Step(id="s", description="d"), calls, IterationGuard("s"),
        step_result="", notes=["be different"],
    )

    roles = [m["role"] for m in executor._conversation_buffer]
    assert roles[:4] == ["tool"] * 4 and roles[4:] == ["system", "system"]
    assert "be different" in executor._conversation_buffer[4]["content"]
