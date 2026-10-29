"""D4: WEEBOT_DB_BACKEND=postgresql gives a backend that can actually run.

Before, the PostgreSQL adapters created no tables (`_ensure_schema` had no caller),
fell back to a `weebot:weebot` DSN, decoded no JSONB, played none of the role
stores the learning loops need, lacked the knowledge graph's
`delete_by_session_id` the delete cascade calls, and the graph was never selected.
These checks need no database; tests/integration/test_postgresql_adapter.py runs
the SQL when WEEBOT_PG_DSN points at one.
"""

import pytest

from weebot.config.secret_accessor import SecretAccessor
from weebot.infrastructure.persistence.postgresql import connection
from weebot.infrastructure.persistence.postgresql.state_repo import PostgreSQLStateRepository


async def test_no_dsn_is_an_error_not_a_default(monkeypatch):
    import asyncpg

    monkeypatch.setattr(SecretAccessor, "get", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(connection, "_pools", {})

    async def refuse(**_k):
        raise AssertionError("no pool should be built without a DSN")

    monkeypatch.setattr(asyncpg, "create_pool", refuse)
    with pytest.raises(RuntimeError, match="WEEBOT_PG_DSN"):
        await connection.get_pool("sessions")


def test_the_domain_database_replaces_the_dsn_database():
    dsn = "postgresql://u:p@h:5432/main?sslmode=require"
    assert connection._build_dsn(dsn, "weebot_skills") == (
        "postgresql://u:p@h:5432/weebot_skills?sslmode=require"
    )


def test_the_repository_plays_every_role_the_sqlite_one_does():
    from weebot.application.ports import state_roles_port as roles
    from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

    repo = PostgreSQLStateRepository()  # abstract gaps would raise TypeError here
    sqlite_roles = [
        base for base in SQLiteStateRepository.__mro__ if base.__module__ == roles.__name__
    ]
    assert sqlite_roles
    for role in sqlite_roles:
        assert isinstance(repo, role), role.__name__


def test_the_backend_flag_selects_both_postgres_adapters(monkeypatch):
    from weebot.application.di import Container
    from weebot.application.ports.state_repo_port import StateRepositoryPort
    from weebot.infrastructure.persistence.postgresql.knowledge_graph import (
        PostgreSQLKnowledgeGraph,
    )

    monkeypatch.setattr(
        SecretAccessor,
        "get",
        staticmethod(lambda name, *a, **k: "postgresql" if name == "WEEBOT_DB_BACKEND" else None),
    )
    container = Container()
    container.configure_knowledge_graph(db_path="unused.db")
    container.register(StateRepositoryPort, lambda: container._create_state_repo("unused.db"))
    assert isinstance(container.get(StateRepositoryPort), PostgreSQLStateRepository)
    assert isinstance(container.get("kg_adapter"), PostgreSQLKnowledgeGraph)


class _Conn:
    def __init__(self, log):
        self.log = log

    async def execute(self, sql, *args):
        self.log.append((sql, args))
        return "DELETE 3"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _Pool:
    def __init__(self):
        self.log = []

    def acquire(self):
        return _Conn(self.log)


async def test_the_graph_deletes_what_a_session_found(monkeypatch):
    from weebot.infrastructure.persistence.postgresql import knowledge_graph as module

    pool = _Pool()

    async def get_pool(_domain="skills"):
        return pool

    monkeypatch.setattr(module, "get_pool", get_pool)
    graph = module.PostgreSQLKnowledgeGraph()
    assert await graph.delete_by_session_id("s1") == 3
    sql, args = pool.log[-1]
    assert "source_session_id = $1" in sql and args == ("s1",)
    assert any("CREATE TABLE IF NOT EXISTS kg_nodes" in s for s, _ in pool.log)


def test_a_new_event_loop_gets_a_new_pool(monkeypatch):
    """A pool belongs to the loop that built it; a second asyncio.run must not reuse it."""
    import asyncio

    import asyncpg

    monkeypatch.setattr(SecretAccessor, "get", staticmethod(lambda *a, **k: "postgresql://h/db"))
    monkeypatch.setattr(connection, "_pools", {})
    monkeypatch.setattr(connection, "_pool_lock", None)
    built = []

    async def fake_create_pool(**_k):
        built.append(object())
        return built[-1]

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
    first = asyncio.run(connection.get_pool("sessions"))
    second = asyncio.run(connection.get_pool("sessions"))
    assert first is not second
    assert len(built) == 2
