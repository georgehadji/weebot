"""ExecutorAgent pauses on a tool call that needs a human (ADR-013, plan B2).

The `approval_required` branch in `executor/_base.py` had no direct test; it
was only reasoned to mirror the `awaiting_human` branch beside it. A tool
answering PENDING (Flow-pause channel) must make the executor emit
ToolApprovalEvent, then WaitForUserEvent with the prompt, and stop the step:
no further LLM turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

from weebot.application.agents.executor import ExecutorAgent
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.ports.approval_port import ToolCallApproval
from weebot.application.services.tool_approval import pending_result
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.event import ToolApprovalEvent, WaitForUserEvent
from weebot.domain.models.plan import Plan, Step

_REQUEST = ToolCallApproval(
    session_id="s1",
    tool_name="pay_tool",
    arguments={"amount": 5},
    fingerprint="f" * 64,
    guard="financial_policy",
    reason="financial tool 'pay_tool' always asks",
    allow_always=None,
)


class _PendingTool(BaseTool):
    async def execute(self, **kwargs):
        return pending_result(_REQUEST)


@dataclass
class _Response:
    content: str = ""
    tool_calls: list = field(default_factory=list)


async def test_the_step_session_reaches_the_tool_call():
    """Found in plan B2c: nothing called ToolExecutor.set_step_context, so the
    approval scope had session "", and Flow pause denied every web approval
    ("a flow pause needs a session")."""
    from weebot.application.services.tool_approval import current_session_id
    from weebot.domain.models.tool_result import ToolResult

    seen: list[str] = []

    class _Probe(BaseTool):
        async def execute(self, **kwargs):
            seen.append(current_session_id())
            return ToolResult(output="ok")

    probe = _Probe(name="probe", description="d", parameters={"type": "object", "properties": {}})
    executor = ExecutorAgent(llm=MagicMock(), tools=ToolCollection(probe))
    calls = 0

    async def _cascade(messages, description):
        nonlocal calls
        calls += 1
        if calls > 1:
            return _Response(content="done")
        call = {"id": "tc1", "type": "function", "function": {"name": "probe", "arguments": "{}"}}
        return _Response(content="probing", tool_calls=[call])

    executor._cascade.call_with_cascade = _cascade
    step = Step(id="st1", description="probe")
    _ = [
        e
        async for e in executor.execute_step(
            Plan(title="t", steps=[step]), step, session_id="sess-42"
        )
    ]
    assert seen == ["sess-42"]


async def test_a_pending_tool_call_pauses_the_step():
    tool = _PendingTool(
        name="pay_tool",
        description="d",
        parameters={"type": "object", "properties": {"amount": {"type": "number"}}},
    )
    executor = ExecutorAgent(llm=MagicMock(), tools=ToolCollection(tool))
    calls = 0

    async def _cascade(messages, description):
        nonlocal calls
        calls += 1
        return _Response(
            content="paying",
            tool_calls=[
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "pay_tool", "arguments": json.dumps({"amount": 5})},
                }
            ],
        )

    executor._cascade.call_with_cascade = _cascade
    step = Step(id="s1", description="pay")
    events = [e async for e in executor.execute_step(Plan(title="t", steps=[step]), step)]

    approvals = [e for e in events if isinstance(e, ToolApprovalEvent)]
    assert len(approvals) == 1
    assert approvals[0].fingerprint == "f" * 64
    assert approvals[0].risk_level == "financial_policy"
    waits = [e for e in events if isinstance(e, WaitForUserEvent)]
    assert waits and "needs your approval" in waits[-1].question
    assert events.index(approvals[0]) < events.index(waits[-1])
    assert calls == 1, "the step kept going after a pause"
