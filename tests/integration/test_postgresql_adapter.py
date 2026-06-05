"""PostgreSQL adapter integration tests — skips if no PG endpoint.

Requires ``WEEBOT_PG_DSN`` or ``WEEBOT_DB_BACKEND=postgresql`` to execute.
Without a live PostgreSQL instance, all tests skip cleanly.
"""
from __future__ import annotations

import os
import pytest

from weebot.infrastructure.persistence.postgresql import POSTGRESQL_AVAILABLE

pytestmark = pytest.mark.skipif(
    not POSTGRESQL_AVAILABLE,
    reason="asyncpg not installed — install with: pip install asyncpg",
)


def _has_pg() -> bool:
    """Check if a PostgreSQL DSN is configured."""
    dsn = os.environ.get("WEEBOT_PG_DSN", "")
    backend = os.environ.get("WEEBOT_DB_BACKEND", "")
    return bool(dsn) or backend.lower() == "postgresql"


_skip_if_no_pg = pytest.mark.skipif(
    not _has_pg(),
    reason="No WEEBOT_PG_DSN or WEEBOT_DB_BACKEND=postgresql configured",
)


@_skip_if_no_pg
class TestPostgreSQLStateRepository:
    """Integration tests for PostgreSQLStateRepository.

    These tests exercise the full persistence contract against a live DB.
    """

    @pytest.mark.asyncio
    async def test_save_and_load_session(self):
        """Session round-trip: save → load returns the same session."""
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )
        from weebot.domain.models.session import Session, SessionContext

        repo = PostgreSQLStateRepository()
        session = Session(id="pg-test-1", context=SessionContext())
        await repo.save_session(session)

        loaded = await repo.load_session("pg-test-1")
        assert loaded is not None, "Session not found after save"
        assert loaded.id == "pg-test-1"
        assert loaded.status.value == "pending"

        await repo.delete_session("pg-test-1")

    @pytest.mark.asyncio
    async def test_update_session_status(self):
        """Status update is reflected on next load."""
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )
        from weebot.domain.models.session import Session, SessionStatus, SessionContext

        repo = PostgreSQLStateRepository()
        session = Session(id="pg-test-2", context=SessionContext())
        await repo.save_session(session)
        await repo.update_session_status("pg-test-2", SessionStatus.RUNNING)

        loaded = await repo.load_session("pg-test-2")
        assert loaded is not None
        assert loaded.status == SessionStatus.RUNNING

        await repo.delete_session("pg-test-2")

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """list_sessions returns saved sessions."""
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )
        from weebot.domain.models.session import Session, SessionContext

        repo = PostgreSQLStateRepository()
        s1 = Session(id="pg-list-1", user_id="u1", context=SessionContext())
        s2 = Session(id="pg-list-2", user_id="u1", context=SessionContext())
        await repo.save_session(s1)
        await repo.save_session(s2)

        sessions = await repo.list_sessions(user_id="u1")
        ids = {s.id for s in sessions}
        assert "pg-list-1" in ids
        assert "pg-list-2" in ids

        await repo.delete_session("pg-list-1")
        await repo.delete_session("pg-list-2")

    @pytest.mark.asyncio
    async def test_search_sessions(self):
        """Full-text search returns matching sessions."""
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )
        from weebot.domain.models.session import Session, SessionContext

        repo = PostgreSQLStateRepository()
        session = Session(
            id="pg-search-1",
            title="Test search session",
            context=SessionContext(),
        )
        await repo.save_session(session)

        results = await repo.search_sessions("test", limit=5)
        assert len(results) > 0, "Search should find the test session"

        await repo.delete_session("pg-search-1")
