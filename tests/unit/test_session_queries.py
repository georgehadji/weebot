"""Unit tests for SessionQueries — session CRUD operations.

Uses an in-memory SQLite database to verify the query contract.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from weebot.domain.models.session import Session, SessionStatus, SessionContext
from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool
from weebot.infrastructure.persistence._session_queries import SessionQueries


@pytest.fixture
async def pool(tmp_path):
    """Create an in-memory connection pool with schema."""
    pool = SQLiteConnectionPool(
        str(tmp_path / "test_sessions.db"),
        max_read_connections=1,
        enable_wal=False,
    )
    async with pool.acquire_write() as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                status TEXT NOT NULL, title TEXT,
                events_json TEXT NOT NULL DEFAULT '[]',
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
    yield pool
    await pool.close()


@pytest.fixture
def queries(pool):
    return SessionQueries(pool)


@pytest.fixture
def sample_session():
    return Session(
        id="s1", user_id="u1", agent_id="a1",
        status=SessionStatus.RUNNING,
        title="Test Session",
        context=SessionContext(last_prompt="hello"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestSessionQueriesCrud:
    async def test_save_and_load(self, queries, sample_session):
        await queries.save(sample_session)
        row = await queries.load("s1")
        assert row is not None
        assert row["id"] == "s1"
        assert row["user_id"] == "u1"
        assert row["status"] == "running"

    async def test_save_is_upsert(self, queries, sample_session):
        await queries.save(sample_session)
        session2 = sample_session.model_copy(update={"title": "Updated Title", "status": SessionStatus.COMPLETED})
        await queries.save(session2)
        row = await queries.load("s1")
        assert row["title"] == "Updated Title"
        assert row["status"] == "completed"

    async def test_list_returns_all(self, queries):
        s1 = Session(
            id="s1", user_id="u1", agent_id="a1", status=SessionStatus.RUNNING,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s2 = Session(
            id="s2", user_id="u2", agent_id="a1", status=SessionStatus.COMPLETED,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await queries.save(s1)
        await queries.save(s2)
        rows = await queries.list()
        assert len(rows) == 2

    async def test_list_filters_by_user_id(self, queries):
        await queries.save(Session(
            id="s1", user_id="u1", agent_id="a1", status=SessionStatus.RUNNING,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        await queries.save(Session(
            id="s2", user_id="u2", agent_id="a1", status=SessionStatus.RUNNING,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        rows = await queries.list(user_id="u1")
        assert len(rows) == 1
        assert rows[0]["user_id"] == "u1"

    async def test_list_filters_by_status(self, queries):
        await queries.save(Session(
            id="s1", user_id="u1", agent_id="a1", status=SessionStatus.RUNNING,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        await queries.save(Session(
            id="s2", user_id="u1", agent_id="a1", status=SessionStatus.COMPLETED,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        rows = await queries.list(status="completed")
        assert len(rows) == 1
        assert rows[0]["status"] == "completed"

    async def test_count_returns_correct_total(self, queries):
        for i in range(3):
            await queries.save(Session(
                id=f"s{i}", user_id=f"u{i}", agent_id="a1",
                status=SessionStatus.RUNNING,
                context=SessionContext(),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
        assert await queries.count() == 3

    async def test_count_filters_by_user(self, queries):
        await queries.save(Session(
            id="s1", user_id="u1", agent_id="a1", status=SessionStatus.RUNNING,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        await queries.save(Session(
            id="s2", user_id="u2", agent_id="a1", status=SessionStatus.RUNNING,
            context=SessionContext(),
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        assert await queries.count(user_id="u1") == 1

    async def test_update_status(self, queries, sample_session):
        await queries.save(sample_session)
        await queries.update_status("s1", SessionStatus.COMPLETED)
        row = await queries.load("s1")
        assert row["status"] == "completed"

    async def test_delete_removes_row(self, queries, sample_session):
        await queries.save(sample_session)
        await queries.delete("s1")
        row = await queries.load("s1")
        assert row is None

    async def test_load_missing_returns_none(self, queries):
        row = await queries.load("nonexistent")
        assert row is None

    async def test_list_with_pagination(self, queries):
        for i in range(5):
            await queries.save(Session(
                id=f"s{i}", user_id="u1", agent_id="a1",
                status=SessionStatus.RUNNING,
                context=SessionContext(),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
        rows = await queries.list(limit=3, offset=1)
        assert len(rows) == 3

    async def test_events_json_is_serialized(self, queries, sample_session):
        """Verify that events are serialized to JSON correctly."""
        from weebot.domain.models.event import MessageEvent
        session = sample_session.add_event(MessageEvent(role="user", message="hello"))
        await queries.save(session)
        row = await queries.load("s1")
        events_raw = json.loads(row["events_json"])
        assert len(events_raw) == 1
        assert events_raw[0]["role"] == "user"
        assert events_raw[0]["message"] == "hello"
