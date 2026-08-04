"""Table-driven tests for dispatch_session_input (T1.5).

One row per SessionStatus, proving the Strategy dispatch table routes to
exactly the verb the plan specifies: PENDING/FAILED → start, WAITING →
resume, RUNNING → steer, COMPLETED → chat. Pure application-layer test —
no FastAPI, no DI container — every collaborator is a plain stub.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.use_cases.dispatch_session_input import (
    SessionInputContext,
    dispatch_session_input,
)
from weebot.domain.models.session import Session, SessionStatus


def _make_ctx(status: SessionStatus, text: str = "hello") -> SessionInputContext:
    session = Session(id="sess-1", user_id="u1", agent_id="a1", status=status)

    state_repo = AsyncMock()
    state_repo.save_session = AsyncMock()

    task_runner = MagicMock()
    task_runner.create_plan_act_factory = MagicMock(return_value=lambda s: MagicMock())
    task_runner.start_session = AsyncMock(side_effect=lambda s, f: s.set_status(SessionStatus.RUNNING))

    tools = MagicMock()
    tools.teardown = AsyncMock()

    steering = AsyncMock()

    return SessionInputContext(
        session=session,
        text=text,
        state_repo=state_repo,
        task_runner=task_runner,
        llm=MagicMock(),
        event_bus=MagicMock(),
        steering=steering,
        build_tools=AsyncMock(return_value=tools),
        build_chat_flow=lambda s, model: MagicMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected_verb",
    [
        (SessionStatus.PENDING, "start"),
        (SessionStatus.FAILED, "start"),
        (SessionStatus.WAITING, "resume"),
        (SessionStatus.RUNNING, "steer"),
        (SessionStatus.COMPLETED, "chat"),
    ],
)
async def test_dispatch_routes_to_expected_verb(status, expected_verb):
    ctx = _make_ctx(status)
    result = await dispatch_session_input(ctx)
    assert result.verb == expected_verb


@pytest.mark.asyncio
async def test_start_strategy_stores_text_as_last_prompt_and_starts_flow():
    ctx = _make_ctx(SessionStatus.PENDING, text="build me a widget")
    result = await dispatch_session_input(ctx)

    ctx.task_runner.create_plan_act_factory.assert_called_once()
    ctx.task_runner.start_session.assert_awaited_once()
    saved_session = ctx.state_repo.save_session.await_args.args[0]
    assert saved_session.context["last_prompt"] == "build me a widget"
    assert result.verb == "start"


@pytest.mark.asyncio
async def test_resume_strategy_appends_user_message_and_sets_running():
    ctx = _make_ctx(SessionStatus.WAITING, text="yes proceed")
    result = await dispatch_session_input(ctx)

    assert result.session.status == SessionStatus.RUNNING
    user_messages = [e for e in result.session.events if getattr(e, "role", None) == "user"]
    assert any(m.message == "yes proceed" for m in user_messages)


@pytest.mark.asyncio
async def test_steer_strategy_sends_via_steering_port_without_mutating_session():
    ctx = _make_ctx(SessionStatus.RUNNING, text="focus on tests")
    result = await dispatch_session_input(ctx)

    ctx.steering.send.assert_awaited_once_with("sess-1", "focus on tests")
    assert result.session is ctx.session  # unchanged — steering doesn't touch session state


@pytest.mark.asyncio
async def test_chat_strategy_starts_a_new_flow_via_task_runner():
    ctx = _make_ctx(SessionStatus.COMPLETED, text="one more question")
    result = await dispatch_session_input(ctx)

    ctx.task_runner.start_session.assert_awaited_once()
    saved_session = ctx.state_repo.save_session.await_args.args[0]
    assert saved_session.context["last_prompt"] == "one more question"
    assert result.verb == "chat"
