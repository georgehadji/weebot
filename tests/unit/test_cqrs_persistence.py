"""Integration tests for CQRS handler persistence.

Verifies that CreatePlanHandler and UpdatePlanHandler append events
to the session and persist via StateRepositoryPort, so the CQRS path
does not silently diverge from PlanActFlow._emit().
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from weebot.application.cqrs.mediator import Mediator
from weebot.application.cqrs.commands import CreatePlanCommand, UpdatePlanCommand
from weebot.application.cqrs.handlers import CreatePlanHandler, UpdatePlanHandler
from weebot.domain.models.event import PlanEvent, PlanStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session
from weebot.infrastructure.persistence.in_memory_state_repo import (
    InMemoryStateRepository,
)


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def state_repo():
    return InMemoryStateRepository()


@pytest.fixture
def sample_session():
    return Session(
        id="test-session-persist",
        user_id="test-user",
    )


@dataclass
class _MockResponse:
    content: str


class _MockLLM:
    """Returns a fixed valid plan JSON, mimicking PlannerAgent's LLM dependency."""

    def __init__(self, plan_dict: dict | None = None):
        self._plan = plan_dict or {
            "title": "Test Plan",
            "message": "A test plan for persistence verification.",
            "steps": [
                {"id": "step-1", "description": "Do step 1", "status": "pending"},
                {"id": "step-2", "description": "Do step 2", "status": "pending"},
            ],
        }
        self.messages: list = []

    async def chat(self, messages, **kwargs) -> _MockResponse:
        self.messages.append(messages)
        return _MockResponse(content=json.dumps(self._plan))


# ── tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_plan_handler_persists_events(state_repo, sample_session):
    """CreatePlanHandler must append events to the session and save it."""
    await state_repo.save_session(sample_session)

    mock_llm = _MockLLM()
    handler = CreatePlanHandler(state_repo=state_repo, llm=mock_llm)

    command = CreatePlanCommand(
        session_id=sample_session.id,
        prompt="Write a test plan",
    )
    result = await handler.handle(command)

    # Handler must return success
    assert result.success, f"Handler failed: {result.error}"
    assert result.data["status"] == "plan_created"

    # Events must be non-empty
    events = result.data.get("events", [])
    assert len(events) > 0, "Handler should have emitted at least one event"

    # Session in the repo must now contain the events
    persisted = await state_repo.load_session(sample_session.id)
    assert persisted is not None, "Session should exist after handler runs"
    assert len(persisted.events) > 0, (
        f"Session should have events after CreatePlanHandler, "
        f"got {len(persisted.events)}"
    )

    # At minimum a PlanEvent should be present
    plan_events = [e for e in persisted.events if e.type == "plan"]
    assert len(plan_events) >= 1, "Session should contain at least one PlanEvent"


@pytest.mark.asyncio
async def test_create_plan_handler_no_session(state_repo):
    """Handler should fail gracefully when session doesn't exist."""
    mock_llm = _MockLLM()
    handler = CreatePlanHandler(state_repo=state_repo, llm=mock_llm)

    command = CreatePlanCommand(
        session_id="nonexistent-session",
        prompt="Write a plan",
    )
    result = await handler.handle(command)

    assert not result.success
    assert result.error_code == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_plan_handler_persists_events(state_repo, sample_session):
    """UpdatePlanHandler must append events to the session and save it."""
    # First, put the session in a state where it HAS a plan
    existing_plan = Plan(
        title="Original Plan",
        message="Original",
        steps=[
            Step(id="step-1", description="Do step 1", status="completed"),
            Step(id="step-2", description="Do step 2", status="pending"),
        ],
    )
    sample_session = sample_session.add_event(
        PlanEvent(status=PlanStatus.CREATED, plan=existing_plan.model_dump())
    )
    await state_repo.save_session(sample_session)

    mock_llm = _MockLLM(
        plan_dict={
            "title": "Updated Plan",
            "message": "Updated plan with new steps.",
            "steps": [
                {"id": "step-1", "description": "Do step 1", "status": "completed"},
                {"id": "step-2", "description": "Do step 2", "status": "pending"},
                {"id": "step-3", "description": "New step 3", "status": "pending"},
            ],
        }
    )
    handler = UpdatePlanHandler(state_repo=state_repo, llm=mock_llm)

    command = UpdatePlanCommand(
        session_id=sample_session.id,
        updates={"reason": "Step 1 completed, adding step 3"},
    )
    result = await handler.handle(command)

    assert result.success, f"Handler failed: {result.error}"
    assert result.data["status"] == "plan_updated"

    events = result.data.get("events", [])
    assert len(events) > 0, "Handler should have emitted at least one event"

    # Verify persistence
    persisted = await state_repo.load_session(sample_session.id)
    assert persisted is not None
    # Should have original PlanEvent + events from update
    assert len(persisted.events) >= 2, (
        f"Session should have at least 2 events (original + update), "
        f"got {len(persisted.events)}"
    )


@pytest.mark.asyncio
async def test_update_plan_handler_no_plan(state_repo, sample_session):
    """Handler should fail when session has no plan."""
    await state_repo.save_session(sample_session)
    mock_llm = _MockLLM()
    handler = UpdatePlanHandler(state_repo=state_repo, llm=mock_llm)

    command = UpdatePlanCommand(
        session_id=sample_session.id,
        updates={"reason": "No plan to update"},
    )
    result = await handler.handle(command)

    assert not result.success
    assert result.error_code == "NO_PLAN_FOUND"


@pytest.mark.asyncio
async def test_mediator_pipeline_persists_via_save_policy(state_repo, sample_session):
    """Full pipeline: mediator → CreatePlanHandler → SavePolicyBehavior → persisted."""
    from weebot.application.cqrs.behaviors.save_policy import SavePolicyBehavior

    await state_repo.save_session(sample_session)

    mock_llm = _MockLLM()
    mediator = Mediator()
    mediator.add_pipeline_behavior(SavePolicyBehavior(state_repo=state_repo))
    mediator.register_command_handler(
        CreatePlanCommand,
        CreatePlanHandler(state_repo=state_repo, llm=mock_llm),
    )

    command = CreatePlanCommand(
        session_id=sample_session.id,
        prompt="Test via mediator",
    )
    result = await mediator.send(command)

    assert result.success, f"Mediator send failed: {result.error}"

    # Verify the session was persisted
    persisted = await state_repo.load_session(sample_session.id)
    assert persisted is not None
    assert len(persisted.events) > 0, (
        "After mediator.send, session must have events from handler + SavePolicyBehavior save"
    )
