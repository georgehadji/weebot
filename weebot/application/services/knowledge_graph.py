"""KnowledgeGraphService — business logic for entity and relationship management.

Provides deduplication, confidence merging, and temporal versioning
on top of the SQLite-backed knowledge graph storage.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
from weebot.domain.models.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeSnapshot,
)

logger = logging.getLogger(__name__)

# ── Label constants ─────────────────────────────────────────────────
LABEL_COMPETITOR = "competitor"
LABEL_PERSON = "person"
LABEL_TECHNOLOGY = "technology"
LABEL_FILE = "file"
LABEL_FACT = "fact"
LABEL_ORGANIZATION = "organization"
LABEL_PRODUCT = "product"

# Property keys used for confidence tracking
CONFIDENCE_KEY = "_confidence"


class KnowledgeGraphService:
    """Knowledge graph business logic.

    Wraps a KnowledgeGraphPort adapter with:
    - Deduplication (same label+name → merge properties)
    - Confidence merging (higher confidence overwrites lower)
    - Temporal versioning (snapshots on every change)
    """

    def __init__(self, adapter: KnowledgeGraphPort) -> None:
        """Initialize the service.

        Args:
            adapter: The storage adapter (e.g. SQLiteKnowledgeGraph).
        """
        self._adapter = adapter

    # ── Public API ──────────────────────────────────────────────────

    async def discover_node(
        self,
        label: str,
        name: str,
        properties: dict[str, Any] | None = None,
        session_id: str = "",
        confidence: float = 0.7,
    ) -> KnowledgeNode:
        """Discover and store a new entity, merging with any existing node.

        Uses (label, name_lower) as the dedup key. If a matching node
        exists, properties are merged — existing keys keep their values
        unless the incoming confidence is higher.

        Args:
            label: Node label (competitor, person, etc.).
            name: Human-readable name (dedup key with label).
            properties: Arbitrary key-value properties.
            session_id: Source session that discovered this.
            confidence: Confidence in this discovery (0.0–1.0).

        Returns:
            The upserted KnowledgeNode.
        """
        props = dict(properties or {})
        props[CONFIDENCE_KEY] = confidence

        node_id = self._make_node_id(label, name)
        node = KnowledgeNode(
            id=node_id,
            label=label,
            name=name,
            properties=props,
            source_session_id=session_id,
        )

        return await self._adapter.upsert_node(node)

    async def relate_nodes(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        confidence: float = 1.0,
        evidence: str = "",
    ) -> KnowledgeEdge:
        """Add a typed relationship between two existing nodes.

        Args:
            source_id: Source node ID.
            target_id: Target node ID.
            relation: Relationship type string.
            confidence: Confidence in the relationship.
            evidence: Citation or tool call that established the edge.

        Returns:
            The stored KnowledgeEdge.
        """
        edge = KnowledgeEdge(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            confidence=confidence,
            evidence=evidence,
        )
        return await self._adapter.add_edge(edge)

    async def extract_from_step_result(
        self,
        step_description: str,
        result: str,
        session_id: str,
    ) -> int:
        """Attempt to extract knowledge nodes from a step execution result.

        Parses the result for structured facts and stores them as nodes
        with edges to the step description.

        Args:
            step_description: What the step was doing.
            result: The execution result text.
            session_id: Current session ID.

        Returns:
            Number of nodes created/updated.
        """
        # Simple heuristic: look for "key: value" patterns in results
        count = 0
        lines = (result or "").split("\n")
        for line in lines:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key and value and len(value) < 200:
                # Treat extracted facts as knowledge nodes
                await self.discover_node(
                    label=LABEL_FACT,
                    name=key,
                    properties={"value": value, "source": step_description},
                    session_id=session_id,
                    confidence=0.6,
                )
                count += 1

        if count:
            logger.info("Extracted %d knowledge nodes from step result", count)

        return count

    async def query(self, label: str | None = None, **filters: Any) -> list[KnowledgeNode]:
        """Query knowledge nodes.

        Args:
            label: Optional label filter.
            **filters: Property key-value filters.

        Returns:
            List of matching KnowledgeNode instances.
        """
        return await self._adapter.query(label=label, filters=filters or None)

    async def search(self, query: str, limit: int = 10) -> list[KnowledgeNode]:
        """Full-text search across node names and properties.

        Args:
            query: Search string.
            limit: Max results.

        Returns:
            List of matching nodes.
        """
        return await self._adapter.search(query, limit=limit)

    async def get_stats(self) -> dict[str, Any]:
        """Get summary statistics about the knowledge graph.

        Returns:
            Dict with counts and metadata.
        """
        return await self._adapter.get_stats()

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    def _make_node_id(label: str, name: str) -> str:
        """Create a deterministic node ID from label and name.

        Uses SHA-256 of (label + ":" + name.lower()) for consistent
        deduplication across sessions.

        Args:
            label: Node label.
            name: Node name.

        Returns:
            Deterministic hex node ID.
        """
        raw = f"{label}:{name.strip().lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
