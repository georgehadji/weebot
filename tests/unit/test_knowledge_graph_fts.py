"""Tests for FTS5 sync triggers on SQLiteKnowledgeGraph.

Verifies that the external-content kg_nodes_fts table is properly
populated by triggers on INSERT/UPDATE/DELETE and that the LIKE
fallback still works when FTS5 is unavailable.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weebot.domain.models.knowledge_graph import (
    CONFIDENCE_KEY,
    CORROBORATION_KEY,
    VALID_FROM_KEY,
    KnowledgeNode,
)
from weebot.application.services.knowledge_graph import (
    DEFAULT_CONFIDENCE_MARGIN,
    merge_properties,
)
from weebot.infrastructure.persistence.sqlite_knowledge_graph import (
    SQLiteKnowledgeGraph,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Return a temporary database path."""
    return str(tmp_path / "test_kg_fts.db")


@pytest.fixture
def kg(db_path: str) -> SQLiteKnowledgeGraph:
    """Create a fresh SQLiteKnowledgeGraph on a temp database."""
    return SQLiteKnowledgeGraph(db_path=db_path)


@pytest.mark.asyncio
async def test_fts_index_populated_on_upsert(kg: SQLiteKnowledgeGraph) -> None:
    """After upserting a node, FTS MATCH should find it (not via LIKE)."""
    node = KnowledgeNode(
        id="test-node-1",
        label="technology",
        name="Python",
        properties={"version": "3.12", "_confidence": 0.9},
    )
    await kg.upsert_node(node)

    # Search via FTS — must find the node
    results = await kg.search("Python", limit=10)
    assert len(results) >= 1
    assert any(n.id == "test-node-1" for n in results)

    # Also verify the FTS table has the row directly
    with kg._get_conn() as conn:
        row = conn.execute(
            "SELECT rowid FROM kg_nodes_fts WHERE kg_nodes_fts MATCH ?",
            ("Python",),
        ).fetchone()
    assert row is not None, "FTS table should have indexed the node"


@pytest.mark.asyncio
async def test_fts_reflects_update(kg: SQLiteKnowledgeGraph) -> None:
    """After updating a node's name, the old term should no longer match."""
    node = KnowledgeNode(
        id="test-node-2",
        label="person",
        name="Alice",
        properties={"_confidence": 0.8},
    )
    await kg.upsert_node(node)

    # Confirm old name is findable
    results = await kg.search("Alice", limit=10)
    assert any(n.id == "test-node-2" for n in results)

    # Update to new name
    updated = KnowledgeNode(
        id="test-node-2",
        label="person",
        name="Bob",
        properties={"_confidence": 0.9},
    )
    await kg.upsert_node(updated)

    # Old name should no longer return the node
    old_results = await kg.search("Alice", limit=10)
    assert not any(n.id == "test-node-2" for n in old_results)

    # New name should return it
    new_results = await kg.search("Bob", limit=10)
    assert any(n.id == "test-node-2" for n in new_results)


@pytest.mark.asyncio
async def test_fts_reflects_delete(kg: SQLiteKnowledgeGraph) -> None:
    """After pruning, deleted nodes should not appear in FTS results."""
    node = KnowledgeNode(
        id="test-node-3",
        label="file",
        name="config.yaml",
        properties={"path": "/etc/config.yaml", "_confidence": 0.5},
    )
    await kg.upsert_node(node)

    # Confirm it's findable
    results = await kg.search("config.yaml", limit=10)
    assert any(n.id == "test-node-3" for n in results)

    # Directly delete the node to test the DELETE trigger
    with kg._get_conn() as conn:
        conn.execute("DELETE FROM kg_snapshots WHERE node_id = ?", ("test-node-3",))
        conn.execute("DELETE FROM kg_edges WHERE source_id = ? OR target_id = ?", ("test-node-3", "test-node-3"))
        conn.execute("DELETE FROM kg_nodes WHERE id = ?", ("test-node-3",))
        conn.commit()

    # Should no longer be in FTS
    results = await kg.search("config.yaml", limit=10)
    assert not any(n.id == "test-node-3" for n in results)


@pytest.mark.asyncio
async def test_fts_properties_match(kg: SQLiteKnowledgeGraph) -> None:
    """FTS should match on properties content, not just name."""
    node = KnowledgeNode(
        id="test-node-4",
        label="fact",
        name="population",
        properties={
            "value": "8.2 million",
            "location": "Berlin",
            "_confidence": 0.7,
        },
    )
    await kg.upsert_node(node)

    # Match on property value
    results = await kg.search("Berlin", limit=10)
    assert any(n.id == "test-node-4" for n in results)

    # Match on property key+value
    results = await kg.search("million", limit=10)
    assert any(n.id == "test-node-4" for n in results)


@pytest.mark.asyncio
async def test_backfill_populates_existing_rows(kg: SQLiteKnowledgeGraph) -> None:
    """The one-time backfill should populate FTS for pre-existing nodes."""
    # Insert a node directly (bypassing upsert → trigger path)
    node = KnowledgeNode(
        id="test-node-5",
        label="technology",
        name="Rust",
        properties={"paradigm": "systems", "_confidence": 0.8},
    )
    with kg._get_conn() as conn:
        conn.execute(
            """INSERT INTO kg_nodes (id, label, name, properties, created_at, source_session_id, version, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node.id, node.label, node.name,
                json.dumps(node.properties),
                node.created_at.isoformat(),
                node.source_session_id,
                node.version,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    # Trigger a re-init — the backfill should fire since FTS is empty
    kg._init_tables()

    # Now search should find it via FTS
    results = await kg.search("Rust", limit=10)
    assert any(n.id == "test-node-5" for n in results)


@pytest.mark.asyncio
async def test_search_falls_back_to_like(db_path: str) -> None:
    """When FTS5 is unavailable, LIKE fallback should still return results."""
    kg = SQLiteKnowledgeGraph(db_path=db_path)

    node = KnowledgeNode(
        id="test-node-6",
        label="fact",
        name="gravity",
        properties={"value": "9.81 m/s²", "_confidence": 0.9},
    )
    await kg.upsert_node(node)

    # Mock FTS5 failure by dropping the FTS table
    # (this simulates a build where fts5 extension is absent)
    try:
        with kg._get_conn() as conn:
            conn.execute("DROP TABLE IF EXISTS kg_nodes_fts")
            conn.execute(
                "DROP TRIGGER IF EXISTS kg_nodes_ai"
            )
            conn.execute(
                "DROP TRIGGER IF EXISTS kg_nodes_ad"
            )
            conn.execute(
                "DROP TRIGGER IF EXISTS kg_nodes_au"
            )
            conn.commit()
    except sqlite3.OperationalError:
        pass  # Some builds may not allow dropping virtual tables

    # Force the adapter to rebuild (FTS won't recreate, triggers won't attach)
    kg._init_tables()

    # Search — should fall through to LIKE and still find the node
    results = await kg.search("gravity", limit=10)
    assert len(results) >= 1
    assert any(n.id == "test-node-6" for n in results)

    # LIKE should also match on property values
    results = await kg.search("9.81", limit=10)
    assert any(n.id == "test-node-6" for n in results)


# ═══════════════════════════════════════════════════════════════════
# Phase 1 — Recency-aware merge policy tests
# ═══════════════════════════════════════════════════════════════════


class TestMergePolicy:
    """Pure-function tests for ``merge_properties()``.

    These test the policy logic in isolation without touching the DB.
    """

    def test_higher_confidence_overwrites(self) -> None:
        """When new confidence exceeds old by >= margin, overwrite."""
        old = {"location": "Berlin", CONFIDENCE_KEY: 0.5}
        new = {"location": "Munich", CONFIDENCE_KEY: 0.7}

        merged = merge_properties(old, new, confidence_margin=0.1)

        assert merged["location"] == "Munich"
        assert merged[CONFIDENCE_KEY] == 0.7

    def test_lower_confidence_does_not_overwrite(self) -> None:
        """When new confidence is lower, old value is preserved."""
        old = {"location": "Berlin", CONFIDENCE_KEY: 0.9}
        new = {"location": "Munich", CONFIDENCE_KEY: 0.3}

        merged = merge_properties(old, new, confidence_margin=0.1)

        assert merged["location"] == "Berlin"
        assert merged[CONFIDENCE_KEY] == 0.9

    def test_recency_overwrites_conflicting_stale(self) -> None:
        """When values conflict and new is more recent, new wins (F3)."""
        old_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new_ts = datetime(2024, 6, 1, tzinfo=timezone.utc)

        old = {"ceo": "Alice", CONFIDENCE_KEY: 0.7, VALID_FROM_KEY: old_ts.isoformat()}
        new = {"ceo": "Bob", CONFIDENCE_KEY: 0.7}

        merged = merge_properties(
            old, new,
            new_timestamp=new_ts,
            recency_margin_seconds=3600,  # 1 hour
        )

        assert merged["ceo"] == "Bob"
        assert merged[VALID_FROM_KEY] == new_ts.isoformat()
        assert CONFIDENCE_KEY in merged

    def test_agreement_bumps_corroboration(self) -> None:
        """When values agree, old is kept and corroboration count increases."""
        old = {"ceo": "Alice", "revenue": "1B", CONFIDENCE_KEY: 0.7}
        new = {"ceo": "Alice", "revenue": "1B", CONFIDENCE_KEY: 0.7}

        merged = merge_properties(old, new, confidence_margin=0.1)

        # Values unchanged (agreement)
        assert merged["ceo"] == "Alice"
        assert merged["revenue"] == "1B"
        # But corroboration bumped
        assert merged[CORROBORATION_KEY] == 2

    def test_new_keys_added_even_with_lower_confidence(self) -> None:
        """New keys from the incoming observation are merged even when
        overall confidence is lower (agreement rule)."""
        old = {"ceo": "Alice", CONFIDENCE_KEY: 0.9}
        new = {"ceo": "Alice", "revenue": "2B", CONFIDENCE_KEY: 0.3}

        merged = merge_properties(old, new, confidence_margin=0.1)

        assert merged["ceo"] == "Alice"  # preserved from old
        assert merged.get("revenue") == "2B"  # added from new
        assert merged[CONFIDENCE_KEY] == 0.9  # old confidence preserved

    def test_metadata_keys_excluded_from_conflict_check(self) -> None:
        """Reserved keys (_confidence, _valid_from) should not trigger
        the conflict path."""
        old = {"ceo": "Alice", CONFIDENCE_KEY: 0.7, VALID_FROM_KEY: "2024-01-01T00:00:00"}
        new = {"ceo": "Alice", CONFIDENCE_KEY: 0.7, VALID_FROM_KEY: "2024-06-01T00:00:00"}

        merged = merge_properties(old, new)

        # Should go to agreement path (corroboration), not recency overwrite
        assert merged["ceo"] == "Alice"
        assert merged[CORROBORATION_KEY] == 2
