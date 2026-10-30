"""PostgreSQL knowledge graph adapter.

Selected with ``WEEBOT_DB_BACKEND=postgresql``. The schema is created on first
use (``_ensure_schema`` had no caller). Nodes record the session that found them,
so ``delete_by_session_id`` can take part in the session-delete cascade; without
it, deleting a session left its entities behind. JSONB values arrive as dicts
(the pool's codec), and the dense leg of hybrid search is not implemented here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
from weebot.domain.models.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSnapshot,
    ScoredNode,
)
from weebot.infrastructure.persistence.postgresql.connection import get_pool

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    name TEXT NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    source_session_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(label, name)
);
ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS source_session_id TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS kg_edges (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_label ON kg_nodes(label);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_session ON kg_nodes(source_session_id);
"""


def _node(row: Any) -> KnowledgeNode:
    return KnowledgeNode(
        id=row["id"],
        label=row["label"],
        name=row["name"],
        properties=row["properties"] or {},
        version=row["version"],
        source_session_id=row.get("source_session_id", "") or "",
    )


class PostgreSQLKnowledgeGraph(KnowledgeGraphPort):
    """PostgreSQL-backed knowledge graph using JSONB + GIN indexes."""

    def __init__(self) -> None:
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _pool(self) -> Any:
        pool = await get_pool("skills")
        if not self._schema_ready:
            async with self._schema_lock:
                if not self._schema_ready:
                    async with pool.acquire() as conn:
                        await conn.execute(_SCHEMA)
                    self._schema_ready = True
        return pool

    async def _ensure_schema(self) -> None:
        await self._pool()

    async def get_node(self, node_id: str) -> KnowledgeNode | None:
        """Fetch a single node by its ID."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM kg_nodes WHERE id = $1", node_id)
            return _node(dict(row)) if row is not None else None

    async def upsert_node(self, node: KnowledgeNode) -> KnowledgeNode:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO kg_nodes (id, label, name, properties, version, source_session_id)
                   VALUES ($1, $2, $3, $4, 1, $5)
                   ON CONFLICT (label, name) DO UPDATE SET
                       properties = kg_nodes.properties || EXCLUDED.properties,
                       version = kg_nodes.version + 1,
                       updated_at = NOW(),
                       -- the first session owns the node; an empty owner is claimed (D-KG)
                       source_session_id = COALESCE(NULLIF(kg_nodes.source_session_id, ''),
                                                    EXCLUDED.source_session_id)
                   RETURNING *""",
                node.id,
                node.label,
                node.name,
                dict(node.properties),
                node.source_session_id or "",
            )
            return _node(dict(row))

    async def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO kg_edges (source_id, target_id, relation, properties)
                   VALUES ($1, $2, $3, $4)
                   RETURNING *""",
                edge.source_id,
                edge.target_id,
                edge.relation,
                dict(edge.properties),
            )
            return KnowledgeEdge(
                source_id=row["source_id"],
                target_id=row["target_id"],
                relation=row["relation"],
                properties=row["properties"] or {},
            )

    async def query(
        self, label: str | None = None, filters: dict[str, Any] | None = None
    ) -> list[KnowledgeNode]:
        from weebot.domain.services.filter_key_validator import validate_filter_keys

        sql = "SELECT * FROM kg_nodes WHERE 1=1"
        params: list[Any] = []
        if label:
            params.append(label)
            sql += f" AND label = ${len(params)}"
        if filters is not None:
            for k, v in validate_filter_keys(filters).items():
                params.append(str(v))
                sql += f" AND properties->>'{k}' = ${len(params)}"
        sql += " LIMIT 100"
        pool = await self._pool()
        async with pool.acquire() as conn:
            return [_node(dict(r)) for r in await conn.fetch(sql, *params)]

    async def get_neighbors(self, node_id: str, depth: int = 1) -> dict[str, list[dict]]:
        """Edges and nodes within *depth* hops of *node_id* (it ignored depth before)."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH RECURSIVE reach(id, hop) AS (
                       SELECT $1::text, 0
                       UNION
                       SELECT CASE WHEN e.source_id = r.id THEN e.target_id ELSE e.source_id END,
                              r.hop + 1
                       FROM kg_edges e JOIN reach r ON r.id IN (e.source_id, e.target_id)
                       WHERE r.hop < $2
                   )
                   SELECT DISTINCT e.id, e.source_id, e.target_id, e.relation, e.properties,
                          s.label AS src_label, s.name AS src_name,
                          t.label AS tgt_label, t.name AS tgt_name
                   FROM kg_edges e
                   JOIN reach r ON r.id IN (e.source_id, e.target_id) AND r.hop < $2
                   JOIN kg_nodes s ON e.source_id = s.id
                   JOIN kg_nodes t ON e.target_id = t.id
                   LIMIT 100""",
                node_id,
                max(1, depth),
            )
        nodes: list[dict] = []
        edges: list[dict] = []
        seen: set[str] = set()
        for r in rows:
            edges.append(dict(r))
            for nid, nlabel, nname in (
                (r["source_id"], r["src_label"], r["src_name"]),
                (r["target_id"], r["tgt_label"], r["tgt_name"]),
            ):
                if nid not in seen:
                    seen.add(nid)
                    nodes.append({"id": nid, "label": nlabel, "name": nname})
        return {"nodes": nodes, "edges": edges}

    async def snapshot(self, node_id: str) -> KnowledgeSnapshot | None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM kg_nodes WHERE id = $1", node_id)
            if row is None:
                return None
            return KnowledgeSnapshot(
                node_id=row["id"],
                node_label=row["label"],
                node_name=row["name"],
                properties=row["properties"] or {},
                version=row["version"],
                timestamp=row["updated_at"],
            )

    async def hybrid_search(
        self,
        query: str,
        *,
        label: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
        dense_weight: float = 0.4,
        sparse_weight: float = 0.4,
        structured_weight: float = 0.2,
    ) -> list[ScoredNode]:
        """Full-text search plus an optional structured filter; no dense leg yet."""
        nodes = await self.search(query, limit=limit)
        if label or filters:
            filtered_ids = {n.id for n in await self.query(label=label, filters=filters)}
            nodes = [n for n in nodes if n.id in filtered_ids]
        norm = 1.0 / max(len(nodes), 1)
        return [
            ScoredNode(node=n, score=1.0 - i * norm, sparse_score=1.0 - i * norm)
            for i, n in enumerate(nodes[:limit])
        ]

    async def search(self, query: str, limit: int = 10) -> list[KnowledgeNode]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM kg_nodes
                   WHERE to_tsvector('english', name || ' ' || properties::text)
                         @@ plainto_tsquery('english', $1)
                   LIMIT $2""",
                query,
                limit,
            )
            return [_node(dict(r)) for r in rows]

    async def get_stats(self) -> dict[str, Any]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT (SELECT COUNT(*) FROM kg_nodes) AS node_count,
                          (SELECT COUNT(*) FROM kg_edges) AS edge_count,
                          (SELECT MIN(created_at) FROM kg_nodes) AS oldest_node,
                          (SELECT MAX(created_at) FROM kg_nodes) AS newest_node"""
            )
            labels = await conn.fetch("SELECT DISTINCT label FROM kg_nodes ORDER BY label")
        stats = dict(row)
        stats["node_labels"] = [r["label"] for r in labels]
        return stats

    async def delete_by_session_id(self, session_id: str) -> int:
        """Delete the nodes a session found (their edges cascade); return the count."""
        pool = await self._pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM kg_nodes WHERE source_session_id = $1 AND source_session_id <> ''",
                session_id,
            )
        return int(status.split()[-1]) if status else 0
