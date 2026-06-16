"""Unit tests for PlanActFlow (replaces deprecated PlanningTool/PlanningFlow)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.application.flows.plan_act_flow import PlanActFlow
from weebot.tools.base import BaseTool, ToolCollection, ToolResult


# ---------------------------------------------------------------------------
# PlanActFlow — replaces deprecated PlanningTool + PlanningFlow
# ---------------------------------------------------------------------------


class MockLLM:
    """Minimal mock LLM returning valid JSON plan responses."""

    def __init__(self):
        self.chat = AsyncMock()
        self.chat.return_value = MagicMock(
            content='{"title":"Test","steps":[{"id":"s1","description":"do it","status":"pending"}]}',
            tool_calls=None,
            model="mock",
            usage={"total_tokens": 10},
        )

    @property
    def _context_window(self) -> int:
        return 128000


async def _make_wired_flow(llm, session):
    """Build a PlanActFlow with a CQRS mediator + state repo.

    PlanningState now requires a Mediator (plan creation flows through the
    CreatePlanCommand handler), so a bare PlanActFlow(llm, tools, session)
    can no longer create a plan.  This wires the minimal CQRS stack used in
    production, backed by an in-memory repo and the mock LLM.
    """
    from weebot.application.cqrs.mediator import Mediator
    from weebot.application.cqrs.handlers import register_default_handlers
    from weebot.infrastructure.persistence.in_memory_state_repo import (
        InMemoryStateRepository,
    )

    repo = InMemoryStateRepository()
    await repo.save_session(session)
    mediator = Mediator()
    register_default_handlers(mediator, repo, llm=llm)
    return PlanActFlow(
        llm=llm,
        tools=ToolCollection(),
        session=session,
        mediator=mediator,
        state_repo=repo,
    )


@pytest.mark.asyncio
async def test_plan_act_flow_creates_plan():
    """PlanActFlow starts in PlanningState and creates a plan."""
    from weebot.domain.models.session import Session

    llm = MockLLM()
    session = Session(id="test-session")
    flow = await _make_wired_flow(llm, session)
    events = []
    async for event in flow.run("test task"):
        events.append(event)
    assert len(events) > 0
    assert any(e.type == "plan" for e in events if hasattr(e, 'type'))


@pytest.mark.asyncio
async def test_plan_act_flow_multiple_events():
    """PlanActFlow yields events including message, title, and plan events."""
    from weebot.domain.models.session import Session

    llm = MockLLM()
    session = Session(id="test-session-2")
    flow = await _make_wired_flow(llm, session)
    event_types = set()
    async for event in flow.run("another task"):
        if hasattr(event, 'type'):
            event_types.add(event.type)
    assert "plan" in event_types
