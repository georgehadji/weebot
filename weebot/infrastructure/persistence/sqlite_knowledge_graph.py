"""SQLiteKnowledgeGraph — SQLite-backed knowledge graph adapter.

Three tables:
- kg_nodes:       Entities with label, name, properties (JSON), versioning
- kg_edges:       Typed relationships between nodes
- kg_snapshots:   Temporal property snapshots for version tracking

Uses FTS5 for full-text search on node names + properties.
Shares the same connection pool as the main state repository.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
from weebot.domain.models.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSnapshot,
)

logger = logging.getLogger(__name__)

# Default cap to prevent unbounded growth
_MAX_NODES = 100_000


class SQLiteKnowledgeGraph(KnowledgeGraphPort):
    """SQLite-backed knowledge graph adapter."""

    def __init__(
        self,
        db_path: str = "./weebot_sessions.db",
        max_nodes: int = _MAX_NODES,
    ) -> None:
        """Initialize the adapter.

        Args:
            db_path: Path to the shared SQLite database.
            max_nodes: Maximum nodes before pruning kicks in.
        """
        self._db_path = db_path
        self._max_nodes = max_nodes
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a shared connection from the pool or create one.

        Uses the standard weebot connection settings (WAL mode).
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    async def _run_db(self, func, *args, **kwargs):
        """Run a synchronous DB operation in a thread pool to avoid blocking the event loop."""
        return await asyncio.to_thread(lambda: func(*args, **kwargs))

    def _init_tables(self) -> None:
        """Create the knowledge graph tables if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    name TEXT NOT NULL,
                    properties TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    source_session_id TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS kg_edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    evidence TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, relation),
                    FOREIGN KEY (source_id) REFERENCES kg_nodes(id),
                    FOREIGN KEY (target_id) REFERENCES kg_nodes(id)
                );

                CREATE TABLE IF NOT EXISTS kg_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    previous_properties TEXT NOT NULL DEFAULT '{}',
                    new_properties TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (node_id) REFERENCES kg_nodes(id)
                );

                CREATE INDEX IF NOT EXISTS idx_kg_nodes_label ON kg_nodes(label);
                CREATE INDEX IF NOT EXISTS idx_kg_nodes_name ON kg_nodes(name);
                CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges(target_id);
                CREATE INDEX IF NOT EXISTS idx_kg_snapshots_node ON kg_snapshots(node_id);
            """)

            # Create FTS5 virtual table for full-text search
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS kg_nodes_fts
                    USING fts5(name, properties, content='kg_nodes', content_rowid='rowid');
                """)

                # ── Sync triggers for external-content FTS5 ─────────────
                # Without these triggers, kg_nodes_fts is never populated
                # and search() silently falls through to the LIKE fallback.
                conn.executescript("""
                    CREATE TRIGGER IF NOT EXISTS kg_nodes_ai
                    AFTER INSERT ON kg_nodes BEGIN
                        INSERT INTO kg_nodes_fts(rowid, name, properties)
                        VALUES (new.rowid, new.name, new.properties);
                    END;

                    CREATE TRIGGER IF NOT EXISTS kg_nodes_ad
                    AFTER DELETE ON kg_nodes BEGIN
                        INSERT INTO kg_nodes_fts(kg_nodes_fts, rowid, name, properties)
                        VALUES ('delete', old.rowid, old.name, old.properties);
                    END;

                    CREATE TRIGGER IF NOT EXISTS kg_nodes_au
                    AFTER UPDATE ON kg_nodes BEGIN
                        INSERT INTO kg_nodes_fts(kg_nodes_fts, rowid, name, properties)
                        VALUES ('delete', old.rowid, old.name, old.properties);
                        INSERT INTO kg_nodes_fts(rowid, name, properties)
                        VALUES (new.rowid, new.name, new.properties);
                    END;
                """)

                # ── One-time backfill for existing rows ─────────────
                # Runs only when the FTS table is empty but kg_nodes has
                # rows — migration-safe and idempotent.
                fts_count = conn.execute(
                    "SELECT COALESCE(COUNT(*), 0) AS cnt FROM kg_nodes_fts"
                ).fetchone()["cnt"]
                node_count = conn.execute(
                    "SELECT COALESCE(COUNT(*), 0) AS cnt FROM kg_nodes"
                ).fetchone()["cnt"]
                if fts_count == 0 and node_count > 0:
                    logger.info(
                        "Backfilling kg_nodes_fts with %d existing nodes",
                        node_count,
                    )
                    conn.execute(
                        "INSERT INTO kg_nodes_fts(kg_nodes_fts) VALUES('rebuild')"
                    )

            except sqlite3.OperationalError:
                # FTS5 may not be available in all SQLite builds
                logger.warning("FTS5 not available — KG full-text search disabled")

            conn.commit()

    # ── Core operations ─────────────────────────────────────────────

    async def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Fetch a single node by its ID."""
        return await self._run_db(self._get_node_sync, node_id)

    def _get_node_sync(self, node_id: str) -> Optional[KnowledgeNode]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM kg_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            return self._row_to_node(row) if row else None

    async def upsert_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Insert or update a knowledge graph node."""
        now = datetime.now(timezone.utc).isoformat()
        props_json = json.dumps(node.properties, default=str)
        return await self._run_db(self._upsert_node_sync, node, now, props_json)

    def _upsert_node_sync(self, node: KnowledgeNode, now: str, props_json: str) -> KnowledgeNode:
        """Synchronous body of upsert_node — runs in thread pool.

        The merge policy (confidence-weighted, recency-aware) lives in
        ``KnowledgeGraphService.merge_properties()`` in the application
        layer.  By the time properties reach this adapter they have
        already been merged by the service.  This method is a simple
        write-through: it persists whatever ``properties`` dict is
        passed, bumps the version, and snapshots the change.
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM kg_nodes WHERE id = ?",
                (node.id,),
            ).fetchone()

            if existing:
                old_props_json = existing["properties"]
                new_version = existing["version"] + 1

                effective_label = node.label or existing["label"]
                effective_name = node.name or existing["name"]

                conn.execute(
                    """UPDATE kg_nodes
                       SET label = ?, name = ?, properties = ?, version = ?, updated_at = ?
                       WHERE id = ?""",
                    (effective_label, effective_name, props_json, new_version, now, node.id),
                )

                # Snapshot the change
                conn.execute(
                    """INSERT INTO kg_snapshots (node_id, timestamp, previous_properties, new_properties)
                       VALUES (?, ?, ?, ?)""",
                    (node.id, now, old_props_json, props_json),
                )

                node = KnowledgeNode(
                    id=node.id,
                    label=effective_label,
                    name=effective_name,
                    properties=node.properties,
                    created_at=datetime.fromisoformat(existing["created_at"]),
                    source_session_id=node.source_session_id or existing["source_session_id"],
                    version=new_version,
                )
            else:
                # New node
                conn.execute(
                    """INSERT INTO kg_nodes (id, label, name, properties, created_at, source_session_id, version, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (node.id, node.label, node.name, props_json,
                     node.created_at.isoformat(), node.source_session_id,
                     node.version, now),
                )

                # Initial snapshot
                conn.execute(
                    """INSERT INTO kg_snapshots (node_id, timestamp, previous_properties, new_properties)
                       VALUES (?, ?, '{}', ?)""",
                    (node.id, now, props_json),
                )

            conn.commit()

            # Prune if over limit
            self._prune_if_needed(conn)

        return node

    async def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        """Add a typed relationship between two nodes."""
        return await self._run_db(self._add_edge_sync, edge)

    def _add_edge_sync(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        """Synchronous body of add_edge — runs in thread pool."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO kg_edges (source_id, target_id, relation, confidence, evidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (edge.source_id, edge.target_id, edge.relation, edge.confidence,
                 edge.evidence, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return edge

    async def query(
        self, label: Optional[str] = None, filters: Optional[dict[str, Any]] = None
    ) -> list[KnowledgeNode]:
        """Query nodes by label and optional property filters."""
        query = "SELECT * FROM kg_nodes WHERE 1=1"
        params: list[Any] = []

        if label:
            query += " AND label = ?"
            params.append(label)

        if filters:
            for key, value in filters.items():
                # Filter by JSON property (simple substring match)
                if isinstance(value, str):
                    query += f" AND properties LIKE ?"
                    params.append(f'%"{key}": "%{value}%"')
                else:
                    query += f" AND properties LIKE ?"
                    params.append(f'%"{key}": {value}%')

        query += " ORDER BY updated_at DESC LIMIT 100"

        return await self._run_db(self._query_sync, query, params)

    def _query_sync(self, query: str, params: list[Any]) -> list[KnowledgeNode]:
        """Synchronous body of query — runs in thread pool."""
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_node(row) for row in rows]

    async def get_neighbors(
        self, node_id: str, depth: int = 1
    ) -> dict[str, list[dict[str, Any]]]:
        """Get neighboring nodes and edges."""
        return await self._run_db(self._get_neighbors_sync, node_id)

    def _get_neighbors_sync(self, node_id: str) -> dict[str, list[dict[str, Any]]]:
        """Synchronous body of get_neighbors — runs in thread pool."""
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        with self._get_conn() as conn:
            # Outgoing edges
            outgoing = conn.execute(
                """SELECT e.*, n.id as nid, n.label, n.name, n.properties
                   FROM kg_edges e
                   JOIN kg_nodes n ON e.target_id = n.id
                   WHERE e.source_id = ?""",
                (node_id,),
            ).fetchall()

            for row in outgoing:
                edges.append(dict(row))
                node = self._row_to_node(row)
                nodes.append(node.model_dump())

            # Incoming edges
            incoming = conn.execute(
                """SELECT e.*, n.id as nid, n.label, n.name, n.properties
                   FROM kg_edges e
                   JOIN kg_nodes n ON e.source_id = n.id
                   WHERE e.target_id = ?""",
                (node_id,),
            ).fetchall()

            for row in incoming:
                edges.append(dict(row))
                node = self._row_to_node(row, prefix="n")
                nodes.append(node.model_dump())

        return {"nodes": nodes, "edges": edges}

    async def snapshot(self, node_id: str) -> Optional[KnowledgeSnapshot]:
        """Get the most recent snapshot of a node's properties."""
        return await self._run_db(self._snapshot_sync, node_id)

    def _snapshot_sync(self, node_id: str) -> Optional[KnowledgeSnapshot]:
        """Synchronous body of snapshot — runs in thread pool."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM kg_snapshots
                   WHERE node_id = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (node_id,),
            ).fetchone()

            if row:
                return KnowledgeSnapshot(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    node_id=row["node_id"],
                    previous_properties=json.loads(row["previous_properties"]),
                    new_properties=json.loads(row["new_properties"]),
                )
        return None

    async def search(self, query: str, limit: int = 10) -> list[KnowledgeNode]:
        """Full-text search across node names and properties."""
        return await self._run_db(self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int = 10) -> list[KnowledgeNode]:
        """Synchronous body of search — runs in thread pool."""
        results: list[KnowledgeNode] = []
        with self._get_conn() as conn:
            # Try FTS5 first
            try:
                rows = conn.execute(
                    """SELECT n.* FROM kg_nodes_fts f
                       JOIN kg_nodes n ON n.rowid = f.rowid
                       WHERE kg_nodes_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, limit),
                ).fetchall()
                results = [self._row_to_node(r) for r in rows]
            except sqlite3.OperationalError:
                # FTS5 not available — fall back to LIKE
                pass

            if not results:
                # Fallback: LIKE search on name and properties
                like_query = f"%{query}%"
                rows = conn.execute(
                    """SELECT * FROM kg_nodes
                       WHERE name LIKE ? OR properties LIKE ?
                       LIMIT ?""",
                    (like_query, like_query, limit),
                ).fetchall()
                results = [self._row_to_node(r) for r in rows]

        return results

    async def get_stats(self) -> dict[str, Any]:
        """Get summary statistics about the knowledge graph."""
        return await self._run_db(self._get_stats_sync)

    def _get_stats_sync(self) -> dict[str, Any]:
        """Synchronous body of get_stats — runs in thread pool."""
        with self._get_conn() as conn:
            node_count = conn.execute("SELECT COUNT(*) as cnt FROM kg_nodes").fetchone()["cnt"]
            edge_count = conn.execute("SELECT COUNT(*) as cnt FROM kg_edges").fetchone()["cnt"]
            snapshot_count = conn.execute("SELECT COUNT(*) as cnt FROM kg_snapshots").fetchone()["cnt"]
            oldest = conn.execute(
                "SELECT MIN(created_at) as oldest FROM kg_nodes"
            ).fetchone()["oldest"]
            newest = conn.execute(
                "SELECT MAX(created_at) as newest FROM kg_nodes"
            ).fetchone()["newest"]

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "snapshot_count": snapshot_count,
            "oldest_node": oldest,
            "newest_node": newest,
            "max_nodes": self._max_nodes,
        }

    # ── Internal helpers ────────────────────────────────────────────

    def _prune_if_needed(self, conn: sqlite3.Connection) -> None:
        """Prune oldest nodes when the graph exceeds max_nodes.

        Removes the oldest 10% of nodes (and their edges/snapshots).
        Called after every upsert_node.
        """
        count = conn.execute("SELECT COUNT(*) as cnt FROM kg_nodes").fetchone()["cnt"]
        if count > self._max_nodes:
            excess = count - int(self._max_nodes * 0.9)
            logger.warning(
                "Knowledge graph has %d nodes (limit: %d). Pruning %d old nodes.",
                count, self._max_nodes, excess,
            )
            # Find the oldest excess nodes to remove
            to_prune = conn.execute(
                "SELECT id FROM kg_nodes ORDER BY updated_at ASC LIMIT ?",
                (excess,),
            ).fetchall()
            ids = tuple(r["id"] for r in to_prune)
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"DELETE FROM kg_snapshots WHERE node_id IN ({placeholders})",
                    ids,
                )
                conn.execute(
                    f"DELETE FROM kg_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                    ids * 2,
                )
                conn.execute(
                    f"DELETE FROM kg_nodes WHERE id IN ({placeholders})",
                    ids,
                )

    @staticmethod
    def _row_to_node(row: sqlite3.Row, prefix: str = "") -> KnowledgeNode:
        """Convert a SQLite row to a KnowledgeNode.

        Args:
            row: SQLite row (dict-like).
            prefix: Optional column prefix (e.g. "n" for aliased columns).

        Returns:
            KnowledgeNode instance.
        """
        def col(name: str) -> Any:
            key = f"{prefix}_{name}" if prefix else name
            return row[key] if key in row.keys() else row.get(name)

        return KnowledgeNode(
            id=col("id"),
            label=col("label"),
            name=col("name"),
            properties=json.loads(col("properties") or "{}"),
            created_at=datetime.fromisoformat(col("created_at")) if col("created_at") else datetime.now(timezone.utc),
            source_session_id=col("source_session_id") or "",
            version=col("version") or 1,
        )
