"""KnowledgeGraphService — business logic for entity and relationship management.

Provides deduplication, confidence-weighted and recency-aware merge
policy, and temporal versioning on top of a KnowledgeGraphPort adapter.

The merge policy lives here (Application layer), NOT in the adapter
(infrastructure layer), respecting Clean Architecture dependency rules.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from weebot.application.ports.knowledge_graph_port import KnowledgeGraphPort
from weebot.domain.models.knowledge_graph import (
    CONFIDENCE_KEY,
    CORROBORATION_KEY,
    VALID_FROM_KEY,
    VALID_TO_KEY,
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

# ── Merge policy defaults ───────────────────────────────────────────
DEFAULT_CONFIDENCE_MARGIN = 0.1
"""Delta threshold: when ``new_confidence - old_confidence >= margin``,
the new value overwrites regardless of recency."""

DEFAULT_RECENCY_MARGIN_SECONDS = 60.0
"""Time delta: if the new observation is more than this many seconds
later than the old one and they conflict, recency breaks the tie."""


def merge_properties(
    old_props: dict[str, Any],
    new_props: dict[str, Any],
    new_timestamp: datetime | None = None,
    old_timestamp: datetime | None = None,
    confidence_margin: float = DEFAULT_CONFIDENCE_MARGIN,
    recency_margin_seconds: float = DEFAULT_RECENCY_MARGIN_SECONDS,
) -> dict[str, Any]:
    """Merge new properties into old ones using the recency-aware policy.

    Policy rules (applied in order):

    1. **Confidence wins:** If ``new_confidence - old_confidence >= margin``,
       the new value overwrites entirely.

    2. **Recency tiebreak (F3):** If the values *conflict* (they assign
       different values to the same key) and the new observation is
       significantly more recent, overwrite.  Stamp ``_valid_from`` on the
       new value; the old value will carry ``_valid_to`` once persisted.

    3. **Agreement / negligible delta:** Keep old values, bump the
       ``_corroboration_count`` key.

    Args:
        old_props: Currently stored properties (from the adapter).
        new_props: Incoming properties from the caller.
        new_timestamp: When the new observation was made (defaults to now).
        old_timestamp: When the old observation was made (inferred from
            ``old_props.get(VALID_FROM_KEY)`` if not provided).
        confidence_margin: Delta needed for confidence to win.
        recency_margin_seconds: Age difference needed for recency to win.

    Returns:
        Merged properties dict.  The caller should pass this to
        ``adapter.upsert_node()``.
    """
    if new_timestamp is None:
        new_timestamp = datetime.now(timezone.utc)

    old_confidence = old_props.get(CONFIDENCE_KEY, 0.0)
    new_confidence = new_props.get(CONFIDENCE_KEY, 0.0)

    # Rule 1: confidence clearly higher → overwrite
    if new_confidence - old_confidence >= confidence_margin:
        merged = dict(old_props)
        merged.update(new_props)
        merged.pop(VALID_TO_KEY, None)
        if VALID_FROM_KEY not in merged:
            merged[VALID_FROM_KEY] = new_timestamp.isoformat()
        return merged

    # Rule 2: values conflict + recency tiebreak
    conflicting = _has_conflict(old_props, new_props)
    if conflicting:
        old_valid_from = old_timestamp
        if old_valid_from is None:
            raw = old_props.get(VALID_FROM_KEY)
            if raw:
                try:
                    old_valid_from = datetime.fromisoformat(raw)
                except (ValueError, TypeError):
                    old_valid_from = datetime.now(timezone.utc)
            else:
                old_valid_from = datetime.now(timezone.utc)

        age_delta = (new_timestamp - old_valid_from).total_seconds()
        if age_delta >= recency_margin_seconds:
            # New is more recent → overwrite, stamp temporal boundaries
            merged = dict(old_props)
            merged.update(new_props)
            merged[VALID_FROM_KEY] = new_timestamp.isoformat()
            merged.pop(VALID_TO_KEY, None)
            # The caller must stamp VALID_TO on the old snapshot separately
            return merged

    # Rule 3: agreement / negligible delta → keep old, bump corroboration
    merged = dict(old_props)
    merged.update({k: v for k, v in new_props.items() if k not in old_props or old_props.get(k) == v})
    merged[CORROBORATION_KEY] = merged.get(CORROBORATION_KEY, 1) + 1
    return merged


def _has_conflict(
    old_props: dict[str, Any], new_props: dict[str, Any]
) -> bool:
    """Return True when the two dicts assign different values to the same key.

    Reserved keys (``_valid_*``, ``_corroboration_*``) and confidence are
    excluded — they are meta-data, not factual claims.
    """
    SKIP_KEYS = frozenset({CONFIDENCE_KEY, VALID_FROM_KEY, VALID_TO_KEY, CORROBORATION_KEY})
    for key in set(old_props.keys()) | set(new_props.keys()):
        if key in SKIP_KEYS:
            continue
        old_val = old_props.get(key)
        new_val = new_props.get(key)
        if old_val is not None and new_val is not None and old_val != new_val:
            return True
    return False


class KnowledgeGraphService:
    """Knowledge graph business logic.

    Wraps a KnowledgeGraphPort adapter with:
    - Deduplication (same label+name → merge properties)
    - Recency-aware merge policy (F3)
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
        exists, properties are merged via ``merge_properties()`` using
        the recency-aware/confidence policy.

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

        # Check for existing node
        existing = await self._adapter.get_node(node_id)
        if existing is not None:
            props = merge_properties(
                old_props=existing.properties,
                new_props=props,
                new_timestamp=datetime.now(timezone.utc),
                old_timestamp=existing.properties.get(VALID_FROM_KEY),
            )

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

    async def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Fetch a single node by ID.

        Args:
            node_id: The node's unique identifier.

        Returns:
            The KnowledgeNode or None.
        """
        return await self._adapter.get_node(node_id)

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
