"""H18d denial breaker: the third refused call in a step, or the sixth in a session, asks a person."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.application.agents.executor._tool_batch import BatchOutcome, ToolBatchRunner
from weebot.application.ports.approval_port import ToolCallApproval
from weebot.application.services import tool_approval
from weebot.application.services.tool_approval import DENIAL_DATA_KEY, DenialBreaker
from weebot.application.services.tool_guards import (
    GuardAction,
    GuardChain,
    GuardedTool,
    GuardVerdict,
)
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.event import ErrorEvent, WaitForUserEvent
from weebot.domain.models.tool_result import ToolResult


def test_the_third_denial_in_a_step_trips_it():
    breaker = DenialBreaker()
    assert [breaker.record("s", "a") for _ in range(3)] == [None, None, "step"]


def test_the_sixth_denial_in_a_session_trips_it_across_steps():
    breaker = DenialBreaker()
    trips = [breaker.record("s", f"step{i % 3}") for i in range(6)]
    assert trips == [None] * 5 + ["session"]


def test_a_trip_starts_a_new_tally_and_sessions_are_separate():
    breaker = DenialBreaker()
    for _ in range(3):
        breaker.record("s", "a")
    assert breaker.record("s", "a") is None
    assert breaker.record("other", "a") is None


def test_forget_session_drops_its_counts():
    breaker = DenialBreaker()
    breaker.record("s", "a")
    breaker.record("s", "a")
    breaker.forget_session("s")
    assert breaker.record("s", "a") is None


def test_a_refused_approval_carries_the_marker():
    request = ToolCallApproval("s", "bash", {"command": "x"}, "fp", "g", "why")
    assert tool_approval.denied_result(request).data[DENIAL_DATA_KEY]


class _Recorder(BaseTool):
    name: str = "bash"
    description: str = "records"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(output="ran")


class _Denies:
    name = "bash_guard"

    def check(self, tool_name, args):
        return GuardVerdict(GuardAction.DENY, self.name, "blocked")


async def test_a_deny_verdict_carries_the_marker():
    tool = GuardedTool.wrap(_Recorder(), GuardChain([_Denies()]), "enforce")
    result = await tool.execute(command="x")
    assert result.is_error and result.data[DENIAL_DATA_KEY]


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(tool_approval, "_BREAKER", DenialBreaker())
    return ToolBatchRunner()


STEP = SimpleNamespace(id="st1", description="build the thing")
DENIED = ToolResult(
    output="", error="Tool call denied by bash_guard: blocked", data={DENIAL_DATA_KEY: True}
)


def test_the_batch_stops_the_step_and_asks_on_the_third_denial(runner):
    outcomes = [BatchOutcome() for _ in range(3)]
    stopped = [runner._denial_loop(STEP, DENIED, o) for o in outcomes]
    assert stopped == [False, False, True]
    last = outcomes[-1]
    assert last.abort_step and "this step" in last.loop_error
    assert [type(e) for e in last.events] == [ErrorEvent, WaitForUserEvent]
    assert "denied by bash_guard" in last.events[1].question
    assert outcomes[0].events == [] and not outcomes[0].abort_step


def test_other_errors_and_successes_are_not_counted(runner):
    outcome = BatchOutcome()
    for result in (ToolResult(output="", error="boom"), ToolResult(output="fine")) * 5:
        assert not runner._denial_loop(STEP, result, outcome)
    assert outcome.events == []
