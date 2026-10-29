"""R19 (audit 2026-10-29): activity counts come from a read model, not empty event lists.

``list_sessions`` skips loading events (on purpose: list views must stay cheap), but the
active-sessions handler and ``/api/chat/history`` counted steps, tool calls and messages
from ``session.events`` anyway, so every count was always 0. ``session_activity`` now
answers with grouped queries over the stored events, and ``count_sessions`` honours the
``status`` filter so ``GET /api/sessions`` reports the right ``total``.
"""

from __future__ import annotations

import os

import pytest

from weebot.application.cqrs.handlers.active_queries import GetActiveSessionsHandler
from weebot.application.cqrs.queries import GetActiveSessionsQuery
from weebot.application.ports.state_repo_port import SessionActivity
from weebot.domain.models.event import MessageEvent, PlanEvent, StepEvent, ToolEvent, ToolStatus
from weebot.domain.models.plan import Plan, Step
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

_BUSY = SessionActivity(steps=2, steps_completed=1, tool_calls=1, messages=2, events=6)


def _busy(sid: str) -> Session:
    plan = Plan(title="t", steps=[Step(id="a", description="a"), Step(id="b", description="b")])
    return Session(
        id=sid,
        user_id="u",
        status=SessionStatus.RUNNING,
        events=[
            MessageEvent(role="user", message="go"),
            PlanEvent(plan=plan),
            ToolEvent(tool_call_id="c1", tool_name="bash", status=ToolStatus.CALLING),
            ToolEvent(tool_call_id="c1", tool_name="bash", status=ToolStatus.CALLED, result="x"),
            StepEvent(step_id="a", status="completed"),
            MessageEvent(message="done a"),
        ],
    )


def _pg_dsn() -> str:
    return os.environ.get("WEEBOT_PG_DSN", "")


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def repo(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStateRepository()
    elif request.param == "sqlite":
        sqlite = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
        yield sqlite
        await sqlite.close()
    else:
        if not _pg_dsn():
            pytest.skip("no WEEBOT_PG_DSN")
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )

        pg = PostgreSQLStateRepository()
        yield pg
        for sid in ("r19-busy", "r19-idle"):
            await pg.delete_session(sid)


@pytest.mark.asyncio
async def test_activity_counts_stored_events(repo):
    await repo.save_session(_busy("r19-busy"))
    await repo.save_session(Session(id="r19-idle", user_id="u"))
    activity = await repo.session_activity(["r19-busy", "r19-idle", "r19-gone"])
    assert activity == {
        "r19-busy": _BUSY,
        "r19-idle": SessionActivity(),
        "r19-gone": SessionActivity(),
    }


@pytest.mark.asyncio
async def test_count_sessions_honours_status(repo):
    await repo.save_session(_busy("r19-busy"))
    await repo.save_session(Session(id="r19-idle", user_id="u"))
    assert await repo.count_sessions(user_id="u", status="running") == 1
    assert await repo.count_sessions(user_id="u") == 2


@pytest.mark.asyncio
async def test_active_sessions_report_real_counts(tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    await repo.save_session(_busy("r19-busy"))
    try:
        result = await GetActiveSessionsHandler(repo).handle(GetActiveSessionsQuery(user_id="u"))
    finally:
        await repo.close()
    row = result.data["sessions"][0]
    assert (row["step_count"], row["steps_completed"], row["tool_calls"]) == (2, 1, 1)
    assert row["elapsed_events"] == 6
