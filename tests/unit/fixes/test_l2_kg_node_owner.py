"""L2 (plan 2026-10-29, decision D-KG): a knowledge-graph node keeps its first owner.

Re-saving a node never touched ``source_session_id``, so a node first written with ``''``
was never claimed, and the SQLite adapter returned the new caller's id while the row kept
the old one. Owner decision D-KG: the first session owns the node; an empty owner is filled
by the next session that saves it.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.knowledge_graph import KnowledgeNode
from weebot.infrastructure.persistence.sqlite_knowledge_graph import SQLiteKnowledgeGraph


def _node(owner: str) -> KnowledgeNode:
    return KnowledgeNode(id="n1", label="Product", name="widget", source_session_id=owner)


@pytest.mark.asyncio
async def test_an_unowned_node_is_claimed_by_the_next_session(tmp_path):
    kg = SQLiteKnowledgeGraph(db_path=str(tmp_path / "kg.db"))
    await kg.upsert_node(_node(""))
    returned = await kg.upsert_node(_node("B"))
    assert returned.source_session_id == "B"
    assert (await kg.get_node("n1")).source_session_id == "B"


@pytest.mark.asyncio
async def test_a_later_session_does_not_take_an_owned_node(tmp_path):
    kg = SQLiteKnowledgeGraph(db_path=str(tmp_path / "kg.db"))
    await kg.upsert_node(_node("A"))
    returned = await kg.upsert_node(_node("C"))
    assert returned.source_session_id == "A"
    assert (await kg.get_node("n1")).source_session_id == "A"
    assert await kg.delete_by_session_id("C") == 0


class _Captured(Exception):
    pass


@pytest.mark.asyncio
async def test_postgres_fills_the_owner_only_when_empty(monkeypatch):
    from weebot.infrastructure.persistence.postgresql import knowledge_graph as module

    seen: list[str] = []

    class _Conn:
        async def execute(self, sql, *args):
            return "OK"

        async def fetchrow(self, sql, *args):
            seen.append(" ".join(sql.split()))
            raise _Captured

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    async def get_pool(_domain="skills"):
        return _Pool()

    monkeypatch.setattr(module, "get_pool", get_pool)
    with pytest.raises(_Captured):
        await module.PostgreSQLKnowledgeGraph().upsert_node(_node("B"))
    assert (
        "source_session_id = COALESCE(NULLIF(kg_nodes.source_session_id, ''), "
        "EXCLUDED.source_session_id)" in seen[0]
    )
