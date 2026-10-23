"""A met termination condition runs CompletedState, not just names it.

The loop set CompletedState and returned before it ran: no terminal session
status, no DoneEvent, and the session stayed RUNNING.
"""

from __future__ import annotations

import types

from weebot.application.flows.plan_act_flow import PlanActFlow, PlanActFlowConfig
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.termination.base import TerminationResult
from weebot.domain.models.event import DoneEvent
from weebot.domain.models.session import Session, SessionStatus


class _LLM:
    async def chat(self, **_):
        return types.SimpleNamespace(content="{}", model="x", usage=None)


class _Always:
    def check(self, ctx):
        return TerminationResult(should_terminate=True, reason="budget")


async def test_the_run_ends_with_a_terminal_status_and_a_done_event():
    flow = PlanActFlow(PlanActFlowConfig(
        llm=_LLM(), tools=ToolCollection(), session=Session(id="s1", task="t"),
        max_iterations=3, termination_conditions=[_Always()]))
    events = [e async for e in flow.run("t")]
    assert any(isinstance(e, DoneEvent) for e in events)
    assert flow._session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED)
