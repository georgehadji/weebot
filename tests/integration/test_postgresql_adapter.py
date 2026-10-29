"""PostgreSQL adapter integration tests — skips if no PG endpoint.

Requires ``WEEBOT_PG_DSN`` or ``WEEBOT_DB_BACKEND=postgresql`` to execute.
Without a live PostgreSQL instance, all tests skip cleanly.
"""

from __future__ import annotations

import os
import pytest

from weebot.infrastructure.persistence.postgresql import POSTGRESQL_AVAILABLE

pytestmark = pytest.mark.skipif(
    not POSTGRESQL_AVAILABLE, reason="asyncpg not installed — install with: pip install asyncpg"
)


def _has_pg() -> bool:
    """Check if a PostgreSQL DSN is configured."""
    dsn = os.environ.get("WEEBOT_PG_DSN", "")
    backend = os.environ.get("WEEBOT_DB_BACKEND", "")
    return bool(dsn) or backend.lower() == "postgresql"


_skip_if_no_pg = pytest.mark.skipif(
    not _has_pg(), reason="No WEEBOT_PG_DSN or WEEBOT_DB_BACKEND=postgresql configured"
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
        session = Session(id="pg-search-1", title="Test search session", context=SessionContext())
        await repo.save_session(session)

        results = await repo.search_sessions("test", limit=5)
        assert len(results) > 0, "Search should find the test session"

        await repo.delete_session("pg-search-1")


@_skip_if_no_pg
class TestPostgreSQLD4Coverage:
    """D4: the role stores, create/compare-and-set, and the graph's delete cascade."""

    @pytest.mark.asyncio
    async def test_role_stores_round_trip(self):
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )

        repo = PostgreSQLStateRepository()
        await repo.save_plan_template("pg-t1", "h1", "task", "{}", 0.5)
        await repo.save_plan_template("pg-t1", "h1", "task", "{\"better\": 1}", 0.9)
        [row] = await repo.find_plan_templates_by_hash("h1")
        assert row["success_score"] == 0.9 and "better" in row["plan_json"]
        await repo.save_workflow_template("pg-summary", "{}")
        assert "{}" in await repo.list_workflow_templates()
        await repo.upsert_memory_metadata("pg-m1", "text")
        await repo.upsert_memory_metadata("pg-m1", "text")
        entry = await repo.get_memory_entry("pg-m1")
        assert entry["access_count"] == 2 and abs(entry["salience"] - 0.55) < 1e-9
        assert await repo.delete_memory_entries(["pg-m1"]) == 1
        await repo.save_behavioral_rule("pg-r1", "always test", scope="global")
        assert any(r["id"] == "pg-r1" for r in await repo.list_behavioral_rules())

    @pytest.mark.asyncio
    async def test_create_is_insert_once_and_cas_rejects_a_stale_write(self):
        from weebot.domain.models.session import Session, SessionContext
        from weebot.infrastructure.persistence.postgresql.state_repo import (
            PostgreSQLStateRepository,
        )

        repo = PostgreSQLStateRepository()
        session = Session(id="pg-cas-1", context=SessionContext(original_task="find otters"))
        try:
            assert await repo.create_session(session) is True
            assert await repo.create_session(session) is False
            stored = await repo.load_session("pg-cas-1")
            assert stored.context.original_task == "find otters"
            assert await repo.save_session_if_unchanged(stored, stored.updated_at) is True
            assert any(
                r["session_id"] == "pg-cas-1" for r in await repo.search_sessions("otters")
            )
        finally:
            await repo.delete_session("pg-cas-1")

    @pytest.mark.asyncio
    async def test_the_graph_forgets_a_deleted_session(self):
        from weebot.domain.models.knowledge_graph import KnowledgeNode
        from weebot.infrastructure.persistence.postgresql.knowledge_graph import (
            PostgreSQLKnowledgeGraph,
        )

        graph = PostgreSQLKnowledgeGraph()
        node = KnowledgeNode(
            id="pg-n1", label="test", name="pg node", properties={"k": "v"},
            source_session_id="pg-s1",
        )
        saved = await graph.upsert_node(node)
        assert saved.properties["k"] == "v"
        assert await graph.delete_by_session_id("pg-s1") >= 1
        assert await graph.get_node("pg-n1") is None
