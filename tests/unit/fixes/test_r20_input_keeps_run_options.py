"""R20 (audit 2026-10-29): ``/input`` keeps the session's model and ponytail mode.

``/run`` read the model and ponytail mode from the session, but ``/input`` passed only the
request's model and never a ponytail mode, so a session created with
``ponytail_mode="ultra"`` and a model lost both on its next start or resume. Both paths
now build ``RunOptions.from_session``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.use_cases.dispatch_session_input import (
    RunOptions,
    SessionInputContext,
    dispatch_session_input,
)
from weebot.domain.models.session import Session, SessionStatus


def _ctx(status: SessionStatus, model: str | None = None) -> SessionInputContext:
    session = Session(id="s1", status=status)
    session.context["model"] = "session/model"
    session.context["ponytail_mode"] = "ultra"
    runner = MagicMock()
    runner.create_plan_act_factory = MagicMock(return_value=lambda s: MagicMock())
    runner.start_session = AsyncMock(side_effect=lambda s, f: s)
    runner.resume_session = AsyncMock(side_effect=lambda *a, **k: session)
    tools = MagicMock()
    tools.teardown = AsyncMock()
    return SessionInputContext(
        session=session,
        text="go",
        state_repo=AsyncMock(),
        task_runner=runner,
        llm=MagicMock(),
        event_bus=MagicMock(),
        steering=AsyncMock(),
        build_tools=AsyncMock(return_value=tools),
        build_chat_flow=lambda s, m: MagicMock(),
        model=model,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [SessionStatus.PENDING, SessionStatus.WAITING])
async def test_input_keeps_the_sessions_options(status):
    ctx = _ctx(status)
    await dispatch_session_input(ctx)
    kw = ctx.task_runner.create_plan_act_factory.call_args.kwargs
    assert (kw["model"], kw["ponytail_mode"]) == ("session/model", "ultra")


@pytest.mark.asyncio
async def test_a_request_model_overrides_the_sessions():
    ctx = _ctx(SessionStatus.WAITING, model="request/model")
    await dispatch_session_input(ctx)
    kw = ctx.task_runner.create_plan_act_factory.call_args.kwargs
    assert (kw["model"], kw["ponytail_mode"]) == ("request/model", "ultra")


def test_an_empty_session_has_no_options():
    assert RunOptions.from_session(Session(id="e")) == RunOptions(None, None)
