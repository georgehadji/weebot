"""A step that stops for a human has not finished, so it must not be reported completed.

Seen live: a research run's steps 3 to 7 each stopped for a tool approval, yet the executor
then emitted `StepEvent(completed)` for each. `Session.get_last_plan()` rebuilds step
statuses from those events, so the plan showed them done; after "approve" the flow went on to the
next step and the approved call never ran. The brief was never written, and the Plan tab said
"6 of 7 done".

A paused step keeps its last status (started, so RUNNING in the plan). The flow already
resumes at the first step that is not done (`Plan.get_next_step`), which is that step.
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
from weebot.domain.models.event import PlanEvent, PlanStatus, StepEvent
from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session
from weebot.domain.models.tool_result import ToolResult

_REQUEST = ToolCallApproval(
    session_id="s1",
    tool_name="pay_tool",
    arguments={"amount": 5},
    fingerprint="f" * 64,
    guard="egress_guard",
    reason="first_time_recipient",
    allow_always=None,
)


class _PendingTool(BaseTool):
    async def execute(self, **kwargs):
        return pending_result(_REQUEST)


class _AsksTool(BaseTool):
    async def execute(self, **kwargs):
        return ToolResult(output="", data={"awaiting_human": True, "question": "Which one?"})


class _OkTool(BaseTool):
    async def execute(self, **kwargs):
        return ToolResult(output="fine")


@dataclass
class _Response:
    content: str = ""
    tool_calls: list = field(default_factory=list)


def _call(name: str) -> dict:
    function = {"name": name, "arguments": json.dumps({})}
    return {"id": "tc1", "type": "function", "function": function}


async def _run(tool: BaseTool, *, then_answer: str | None = None):
    executor = ExecutorAgent(llm=MagicMock(), tools=ToolCollection(tool))
    calls = 0

    async def _cascade(messages, description):
        nonlocal calls
        calls += 1
        if then_answer is not None and calls > 1:
            return _Response(content=then_answer)
        return _Response(content="working", tool_calls=[_call(tool.name)])

    executor._cascade.call_with_cascade = _cascade
    step = Step(id="s1", description="do the thing")
    plan = Plan(title="t", steps=[step, Step(id="s2", description="later")])
    events = [e async for e in executor.execute_step(plan, step)]
    return plan, events


def _step_statuses(events) -> list[str]:
    return [str(getattr(e.status, "value", e.status)) for e in events if isinstance(e, StepEvent)]


def _tool(cls, name="pay_tool"):
    return cls(name=name, description="d", parameters={"type": "object", "properties": {}})


async def test_a_step_waiting_for_a_tool_approval_is_not_reported_completed():
    _, events = await _run(_tool(_PendingTool))
    assert _step_statuses(events) == ["started"]


async def test_a_step_waiting_for_an_answer_is_not_reported_completed():
    _, events = await _run(_tool(_AsksTool, "ask_tool"))
    assert _step_statuses(events) == ["started"]


async def test_the_session_still_has_the_paused_step_to_do():
    plan, events = await _run(_tool(_PendingTool))
    session = Session(id="s1", user_id="u", agent_id="a").add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=plan.model_dump())
    )
    for event in events:
        session = session.add_event(event)

    derived = session.get_last_plan()
    assert derived.steps[0].status is StepStatus.RUNNING
    assert derived.get_next_step().id == "s1", "the flow would resume at the next step"


async def test_a_step_that_finishes_is_still_reported_completed():
    """Regression guard: only a pause changes the ending."""
    _, events = await _run(_tool(_OkTool, "ok_tool"), then_answer="all done")
    assert _step_statuses(events) == ["started", "completed"]
