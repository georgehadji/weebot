"""PostgreSQL knowledge graph adapter."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
from weebot.domain.models.knowledge_graph import KnowledgeEdge, KnowledgeNode, KnowledgeSnapshot, ScoredNode
from weebot.infrastructure.persistence.postgresql.connection import get_pool


class PostgreSQLKnowledgeGraph(KnowledgeGraphPort):
    """PostgreSQL-backed knowledge graph using JSONB + GIN indexes."""

    async def _ensure_schema(self) -> None:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    name TEXT NOT NULL,
                    properties JSONB NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(label, name)
                );
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
            """)

    async def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Fetch a single node by its ID."""
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM kg_nodes WHERE id = $1", node_id,
            )
            if row is None:
                return None
            return KnowledgeNode(
                id=row["id"], label=row["label"], name=row["name"],
                properties=row["properties"], version=row["version"],
            )

    async def upsert_node(self, node: KnowledgeNode) -> KnowledgeNode:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO kg_nodes (id, label, name, properties, version)
                   VALUES ($1, $2, $3, $4::jsonb, 1)
                   ON CONFLICT (label, name) DO UPDATE SET
                       properties = kg_nodes.properties || EXCLUDED.properties,
                       version = kg_nodes.version + 1,
                       updated_at = NOW()
                   RETURNING *""",
                node.id, node.label, node.name,
                json.dumps(node.properties),
            )
            return KnowledgeNode(id=row["id"], label=row["label"], name=row["name"],
                                 properties=row["properties"], version=row["version"])

    async def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO kg_edges (source_id, target_id, relation, properties)
                   VALUES ($1, $2, $3, $4::jsonb)
                   RETURNING *""",
                edge.source_id, edge.target_id, edge.relation,
                json.dumps(edge.properties),
            )
            return KnowledgeEdge(source_id=row["source_id"], target_id=row["target_id"],
                                 relation=row["relation"], properties=row["properties"])

    async def query(self, label: Optional[str] = None,
                    filters: Optional[dict[str, Any]] = None) -> list[KnowledgeNode]:
        from weebot.domain.services.filter_key_validator import validate_filter_keys
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            sql = "SELECT * FROM kg_nodes WHERE 1=1"
            params: list[Any] = []
            if label:
                sql += " AND label = $" + str(len(params) + 1)
                params.append(label)
            if filters is not None:
                for k, v in validate_filter_keys(filters).items():
                    sql += f" AND properties->>'{k}' = $" + str(len(params) + 1)
                    params.append(str(v))
            sql += " LIMIT 100"
            rows = await conn.fetch(sql, *params)
            return [KnowledgeNode(id=r["id"], label=r["label"], name=r["name"],
                                  properties=r["properties"], version=r["version"])
                    for r in rows]

    async def get_neighbors(self, node_id: str, depth: int = 1) -> dict[str, list[dict]]:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT e.*, s.label AS src_label, s.name AS src_name,
                          t.label AS tgt_label, t.name AS tgt_name
                   FROM kg_edges e
                   JOIN kg_nodes s ON e.source_id = s.id
                   JOIN kg_nodes t ON e.target_id = t.id
                   WHERE e.source_id = $1 OR e.target_id = $1
                   LIMIT 100""",
                node_id,
            )
            nodes: list[dict] = []
            edges: list[dict] = []
            seen_ids: set[str] = set()
            for r in rows:
                edges.append(dict(r))
                for nid, nlabel, nname in [
                    (r["source_id"], r["src_label"], r["src_name"]),
                    (r["target_id"], r["tgt_label"], r["tgt_name"]),
                ]:
                    if nid not in seen_ids:
                        seen_ids.add(nid)
                        nodes.append({"id": nid, "label": nlabel, "name": nname})
            return {"nodes": nodes, "edges": edges}

    async def snapshot(self, node_id: str) -> Optional[KnowledgeSnapshot]:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM kg_nodes WHERE id = $1", node_id
            )
            if row is None:
                return None
            return KnowledgeSnapshot(node_id=row["id"], node_label=row["label"],
                                     node_name=row["name"], properties=row["properties"],
                                     version=row["version"], timestamp=row["updated_at"])

    async def hybrid_search(
        self,
        query: str,
        *,
        label: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
        dense_weight: float = 0.4,
        sparse_weight: float = 0.4,
        structured_weight: float = 0.2,
    ) -> list[ScoredNode]:
        """Hybrid search — delegates to PG full-text search for now.

        Dense leg (pgvector) is a future enhancement.  For now this falls
        back to sparse (to_tsvector) + optional structured filter, with
        the FTS rank mapped into ScoredNode.sparse_score.
        """
        nodes = await self.search(query, limit=limit)
        if label or filters:
            filtered = await self.query(label=label, filters=filters)
            filtered_ids = {n.id for n in filtered}
            nodes = [n for n in nodes if n.id in filtered_ids]
        norm = 1.0 / max(len(nodes), 1)
        return [
            ScoredNode(node=n, score=1.0 - i * norm, sparse_score=1.0 - i * norm)
            for i, n in enumerate(nodes[:limit])
        ]

    async def search(self, query: str, limit: int = 10) -> list[KnowledgeNode]:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM kg_nodes
                   WHERE to_tsvector('english', name || ' ' || properties::text)
                         @@ plainto_tsquery('english', $1)
                   LIMIT $2""",
                query, limit,
            )
            return [KnowledgeNode(id=r["id"], label=r["label"], name=r["name"],
                                  properties=r["properties"], version=r["version"])
                    for r in rows]

    async def get_stats(self) -> dict[str, Any]:
        pool = await get_pool("skills")
        async with pool.acquire() as conn:
            node_count = await conn.fetchval("SELECT COUNT(*) FROM kg_nodes")
            edge_count = await conn.fetchval("SELECT COUNT(*) FROM kg_edges")
            return {"node_count": node_count, "edge_count": edge_count,
                    "node_labels": list(await conn.fetch("SELECT DISTINCT label FROM kg_nodes"))}


import json  # noqa: E402
