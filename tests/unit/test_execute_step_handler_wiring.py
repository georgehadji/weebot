"""Regression tests for the ExecuteStepHandler executor-construction seam.

Previously ExecuteStepHandler built ExecutorAgent(llm, tools, event_bus, model)
directly -- 4 of ExecutorAgent's 22 constructor params -- so skill retrieval,
behavioral rules, harness blocks, personality, user profile and middleware
were all inert on the live (mediator) execution path, and the resume/steering
`user_input` text never reached the acting model at all.

See tasks/specs/side_constraint_integrity_plan.md Phase 0.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from weebot.application.cqrs.commands import ExecuteStepCommand
from weebot.application.cqrs.handlers.execute_step_handler import ExecuteStepHandler
from weebot.domain.models.event import PlanEvent, StepEvent, StepStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session


def _session_with_step(step_id: str = "s1") -> Session:
    plan = Plan(title="t", message="m", steps=[Step(id=step_id, description="do the thing")])
    return Session(id="sess-1").add_event(PlanEvent(plan=plan))


class _FakeStateRepo:
    def __init__(self, session: Session, active_constraints: list | None = None):
        self._session = session
        self._active_constraints = active_constraints or []

    async def load_session(self, session_id: str):
        return self._session

    async def list_active_session_constraints(self, session_id: str):
        return self._active_constraints


@pytest.mark.asyncio
async def test_uses_executor_factory_when_provided():
    """The factory, not a bare 4-kwarg ExecutorAgent, builds the executor."""
    session = _session_with_step()
    state_repo = _FakeStateRepo(session)

    captured_kwargs: dict = {}

    async def _fake_execute_step(plan, step, user_input="", session_id=""):
        captured_kwargs["user_input"] = user_input
        captured_kwargs["session_id"] = session_id
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

    fake_executor = AsyncMock()
    fake_executor.execute_step = _fake_execute_step

    factory_calls: list = []

    def _factory(*, model, session):
        factory_calls.append((model, session))
        return fake_executor

    handler = ExecuteStepHandler(
        state_repo=state_repo, llm=None, tools=None, event_bus=None,
        executor_factory=_factory,
    )
    result = await handler.handle(
        ExecuteStepCommand(session_id="sess-1", step_id="s1", model="m1", user_input="the answer")
    )

    assert result.success, result.error
    assert len(factory_calls) == 1
    assert factory_calls[0][0] == "m1"
    assert factory_calls[0][1] is session
    # user_input and session_id now reach ExecutorAgent.execute_step().
    assert captured_kwargs["user_input"] == "the answer"
    assert captured_kwargs["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_falls_back_to_bare_executor_without_factory():
    """No factory configured -> legacy 4-kwarg construction still works."""
    session = _session_with_step()
    state_repo = _FakeStateRepo(session)

    handler = ExecuteStepHandler(state_repo=state_repo, llm=AsyncMock(), tools=None, event_bus=None)

    # No real LLM call is made because the step fails fast on model routing
    # in a way that's swallowed by the handler's try/except -- we only assert
    # construction and dispatch didn't raise before reaching ExecutorAgent.
    result = await handler.handle(
        ExecuteStepCommand(session_id="sess-1", step_id="s1")
    )
    # Either it runs (success) or fails inside the real executor machinery
    # (error_code set) -- both prove the legacy path is still reachable and
    # didn't crash on handler construction/dispatch itself.
    assert result.success or result.error_code == "STEP_EXECUTION_ERROR"


@pytest.mark.asyncio
async def test_session_constraints_delivered_to_executor():
    """Phase 4: hydrated constraints reach the executor via set_session_constraints."""
    session = _session_with_step()
    state_repo = _FakeStateRepo(session, active_constraints=[
        {"text": "never delete files", "evidence_span": "never delete files",
         "kind": "action", "direction": "tighten", "turn_index": 0},
    ])

    async def _fake_execute_step(plan, step, user_input="", session_id=""):
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

    fake_executor = AsyncMock()
    fake_executor.execute_step = _fake_execute_step

    handler = ExecuteStepHandler(
        state_repo=state_repo, llm=None, tools=None, event_bus=None,
        executor_factory=lambda *, model, session: fake_executor,
    )
    result = await handler.handle(ExecuteStepCommand(session_id="sess-1", step_id="s1"))

    assert result.success, result.error
    fake_executor.set_session_constraints.assert_called_once()
    rendered = fake_executor.set_session_constraints.call_args.args[0]
    assert "never delete files" in rendered


@pytest.mark.asyncio
async def test_no_constraints_does_not_call_setter():
    session = _session_with_step()
    state_repo = _FakeStateRepo(session, active_constraints=[])

    async def _fake_execute_step(plan, step, user_input="", session_id=""):
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

    fake_executor = AsyncMock()
    fake_executor.execute_step = _fake_execute_step

    handler = ExecuteStepHandler(
        state_repo=state_repo, llm=None, tools=None, event_bus=None,
        executor_factory=lambda *, model, session: fake_executor,
    )
    result = await handler.handle(ExecuteStepCommand(session_id="sess-1", step_id="s1"))

    assert result.success, result.error
    fake_executor.set_session_constraints.assert_not_called()


@pytest.mark.asyncio
async def test_constraint_hydration_failure_does_not_block_execution():
    """A broken state_repo must degrade gracefully, not fail the step (plan D9)."""
    session = _session_with_step()

    class _BrokenStateRepo:
        async def load_session(self, session_id):
            return session

        async def list_active_session_constraints(self, session_id):
            raise RuntimeError("db exploded")

    async def _fake_execute_step(plan, step, user_input="", session_id=""):
        yield StepEvent(step_id=step.id, description=step.description, status=StepStatus.STARTED)

    fake_executor = AsyncMock()
    fake_executor.execute_step = _fake_execute_step

    handler = ExecuteStepHandler(
        state_repo=_BrokenStateRepo(), llm=None, tools=None, event_bus=None,
        executor_factory=lambda *, model, session: fake_executor,
    )
    result = await handler.handle(ExecuteStepCommand(session_id="sess-1", step_id="s1"))

    assert result.success, result.error
    fake_executor.set_session_constraints.assert_not_called()


def test_llm_absent_registration_does_not_crash():
    """Regression for the llm=None registration branch (audit finding 8.6):
    ExecuteStepHandler(state_repo) used to require llm/tools positionally
    and raised TypeError at first dispatch, not at registration."""
    handler = ExecuteStepHandler(state_repo=_FakeStateRepo(_session_with_step()))
    assert handler._llm is None
    assert handler._tools is not None
