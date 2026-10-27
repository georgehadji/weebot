"""Tool errors stay distinct for the loop detector, and every result reaches the model.

Found on live session de5d0990: (1) the trajectory monitor hashed ``result.output or ""``,
and an error result has an empty output, so any three errors from three different tools
looked like "Different tool calls producing identical output"; (2) on that diagnosis the
batch skipped the result entirely, so the model saw a "[RECOVERY] switch tools" hint
but never the error, and the UI showed calls without a result (18 of 30).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from weebot.application.agents.executor._tool_batch import ToolBatchRunner
from weebot.application.services.trajectory_monitor import TrajectoryMonitor
from weebot.domain.models.event import ErrorEvent, ToolEvent, ToolStatus
from weebot.domain.models.tool_result import ToolResult
from weebot.domain.models.trajectory import TrajectoryHealth

STEP = SimpleNamespace(id="step-1", description="List the files in Downloads")


def _executor(results):
    return SimpleNamespace(
        _trajectory_monitor=TrajectoryMonitor(),
        _max_steps=40,
        _tools=None,
        _conversation_buffer=[],
        _middleware_chain=None,
        _facts={},
        _present_tool_output=AsyncMock(side_effect=lambda name, result: str(result)),
        _vision_enabled=lambda: False,
        _tool_executor=SimpleNamespace(execute_tool_batch=AsyncMock(side_effect=results)),
    )


_GUARD = SimpleNamespace(record_tool_call=lambda _s: None, is_tool_signature_loop=lambda: False)


async def _run(calls_and_errors):
    """One single-call batch per (tool, error), like the live session."""
    executor = _executor([[ToolResult(error=err)] for _, err in calls_and_errors])
    runner, events = ToolBatchRunner(), []
    for i, (tool, _) in enumerate(calls_and_errors):
        call = {"id": f"c{i}", "function": {"name": tool, "arguments": f'{{"n": {i}}}'}}
        outcome = await runner.run(executor, STEP, [call], _GUARD, step_result="")
        events.extend(outcome.events)
        if outcome.abort_step:
            break
    return executor, events


def test_different_errors_are_not_identical_output():
    monitor = TrajectoryMonitor()
    for i, tool in enumerate(["powershell", "bash", "python_execute"]):
        diagnosis = monitor.diagnose(
            step_id="s", tool_signature=tool, tool_output="", error=f"error number {i}"
        )
    assert diagnosis.health != TrajectoryHealth.SEMANTIC_LOOP


async def test_three_different_failures_do_not_abort_the_step():
    executor, events = await _run(
        [("powershell", "access denied"), ("bash", "not found"), ("python_execute", "timeout")]
    )
    assert not [e for e in events if isinstance(e, ErrorEvent)]
    assert not [m for m in executor._conversation_buffer if "[RECOVERY]" in m["content"]]


async def test_every_result_reaches_the_model_and_the_ui_during_a_loop_hint():
    same = "Failed to start process: NotImplementedError"
    executor, events = await _run([("powershell", same), ("bash", same), ("python_execute", same)])

    called = [e for e in events if isinstance(e, ToolEvent) and e.status == ToolStatus.CALLED]
    assert [e.tool_call_id for e in called] == ["c0", "c1", "c2"]
    assert all(same in e.result for e in called)

    buffer = executor._conversation_buffer
    tool_ids = [m["tool_call_id"] for m in buffer if m["role"] == "tool"]
    assert tool_ids == ["c0", "c1", "c2"]
    # The hint follows the tool message: nothing may sit between a call and its answer.
    hint = next(i for i, m in enumerate(buffer) if "[RECOVERY]" in m["content"])
    assert buffer[hint - 1].get("tool_call_id") == "c2"


async def test_the_result_that_aborts_the_step_is_still_shown():
    same = "Failed to start process: NotImplementedError"
    tools = ["powershell", "bash", "python_execute", "file_editor", "web_search", "glob"]
    _, events = await _run([(t, same) for t in tools])

    abort = next(i for i, e in enumerate(events) if isinstance(e, ErrorEvent))
    last = events[abort - 1]
    assert isinstance(last, ToolEvent) and last.status == ToolStatus.CALLED
