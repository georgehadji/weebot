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
    ScoredNode,
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


# ── Reciprocal Rank Fusion (Phase 2) ───────────────────────────────

RRF_K = 60
"""Default RRF constant. K=60 is the standard value from the fusion literature."""


def reciprocal_rank_fusion(
    sparse: list[tuple[str, float]],
    dense: list[tuple[str, float]],
    structured_ids: set[str],
    *,
    k: float = RRF_K,
    sparse_weight: float = 0.4,
    dense_weight: float = 0.4,
    structured_weight: float = 0.2,
    limit: int = 10,
) -> list[ScoredNode]:
    """Fuse three ranked result sets using Reciprocal Rank Fusion.

    Args:
        sparse: (node_id, raw_score) from FTS5, ordered by rank ASC.
        dense: (node_id, similarity) from cosine, ordered DESC.
        structured_ids: Set of node_ids matching the label/filter query.
        k: RRF constant (default 60).
        sparse_weight: Weight for the sparse leg.
        dense_weight: Weight for the dense leg.
        structured_weight: Weight for the structured leg.
        limit: Max results.

    Returns:
        ScoredNode list sorted by descending fused score.
        Each ScoredNode has ``score`` (fused), ``sparse_score``,
        ``dense_score``, ``structured_score`` (normalized 0-1 components),
        but ``node`` will be None — the caller must hydrate nodes.
    """
    sparse_rank = {nid: i + 1 for i, (nid, _) in enumerate(sparse)}
    dense_rank = {nid: i + 1 for i, (nid, _) in enumerate(dense)}

    all_ids: set[str] = set()
    for nid, _ in sparse:
        all_ids.add(nid)
    for nid, _ in dense:
        all_ids.add(nid)
    all_ids.update(structured_ids)

    MISSING = limit * 3
    scored: list[ScoredNode] = []

    for nid in all_ids:
        in_sparse = nid in sparse_rank
        in_dense = nid in dense_rank
        in_struct = nid in structured_ids

        sr = sparse_rank.get(nid, MISSING)
        dr = dense_rank.get(nid, MISSING)

        sr_score = sparse_weight / (k + sr) if sparse_weight > 0 and in_sparse else 0.0
        dr_score = dense_weight / (k + dr) if dense_weight > 0 and in_dense else 0.0
        st_score = (structured_weight / (k + 1)
                    if in_struct and structured_weight > 0
                    else 0.0)
        fused = sr_score + dr_score + st_score
        scored.append(ScoredNode(
            node=None,  # caller hydrates
            score=min(fused, 1.0),
            sparse_score=min(sr_score / sparse_weight, 1.0) if sparse_weight > 0 and in_sparse else 0.0,
            dense_score=min(dr_score / dense_weight, 1.0) if dense_weight > 0 and in_dense else 0.0,
            structured_score=min(st_score / structured_weight, 1.0) if structured_weight > 0 and in_struct else 0.0,
        ))

    scored.sort(key=lambda x: -x.score)
    return scored[:limit]


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
        user_input: str | None = None,
    ) -> int:
        """Extract knowledge nodes from a step execution result (F7).

        Uses a cheap heuristic: scans for ``key: value`` lines in *result*.
        Each match stores:
        - The extracted ``value`` as a property
        - The **surrounding lines** (±2 context) as ``evidence``
        - Both the tool output (*result*) and optional *user_input* context

        Args:
            step_description: What the step was doing.
            result: The execution result text (tool output).
            session_id: Current session ID.
            user_input: Optional user message that preceded this step.
                When provided, it is stored as ``user_context`` on each
                extracted node so both sides of the turn survive.

        Returns:
            Number of nodes created/updated.
        """
        count = 0
        lines = (result or "").split("\n")
        original_lines = list(lines)  # Keep non-stripped for context extraction

        for i, raw_line in enumerate(original_lines):
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if not key or not value or len(value) >= 200:
                continue

            # Capture surrounding context as evidence (F7: preserve multi-hop)
            start = max(0, i - 2)
            end = min(len(original_lines), i + 3)
            surrounding = "\n".join(original_lines[start:end])

            evidence_lines = [f"line {i + 1}: {raw_line.strip()}"]
            if surrounding:
                evidence_lines.append(f"context:\n{surrounding}")

            props: dict[str, Any] = {
                "value": value,
                "source": step_description,
                "evidence": "\n---\n".join(evidence_lines),
            }

            # Store user context when available (F7: keep both turns)
            if user_input:
                props["user_context"] = user_input.strip()[:500]

            await self.discover_node(
                label=LABEL_FACT,
                name=key,
                properties=props,
                session_id=session_id,
                confidence=0.6,
            )
            count += 1

        if count:
            logger.info("Extracted %d knowledge nodes from step result", count)

        return count

    async def extract_with_llm(
        self,
        step_description: str,
        result: str,
        session_id: str,
        llm: Any = None,
        user_input: str | None = None,
    ) -> int:
        """Extract entity–relation triplets using an LLM (gated).

        This is an **optional** enhancement to the heuristic extraction.
        Pass an *llm* with a ``chat()`` method (following ``LLMPort``
        semantics) to enable schema-constrained triplet extraction.
        When *llm* is ``None`` (the default), this method is a no-op
        returning 0 — the caller must explicitly opt in.

        Args:
            step_description: What the step was doing.
            result: The tool output text.
            session_id: Current session ID.
            llm: Optional LLMPort-compatible provider. If ``None``, skips.
            user_input: Optional user message for context.

        Returns:
            Number of triplets stored.
        """
        if llm is None:
            logger.debug("extract_with_llm skipped — no LLM provider passed")
            return 0

        # Build a structured extraction prompt
        prompt = (
            "Extract entity-relation triplets from the following text. "
            "Return a JSON list of {head, relation, tail, confidence} objects. "
            "Example:\n"
            '[{"head": "Python", "relation": "is_a", "tail": "programming_language", "confidence": 1.0}]\n\n'
            f"Tool output:\n{result[:3000]}\n"
        )
        if user_input:
            prompt = f"User query:\n{user_input[:1000]}\n\n{prompt}"

        try:
            if hasattr(llm, "chat"):
                response = await llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                content = response.get("content", "") if isinstance(response, dict) else str(response)
            else:
                logger.warning("LLM provider lacks chat() method — skipping extraction")
                return 0

            import json as _json
            triplets = _json.loads(content)
            if isinstance(triplets, dict) and "triplets" in triplets:
                triplets = triplets["triplets"]
            if not isinstance(triplets, list):
                return 0

            count = 0
            for t in triplets:
                head = t.get("head", "").strip()
                relation = t.get("relation", "").strip()
                tail = t.get("tail", "").strip()
                confidence = float(t.get("confidence", 0.7))

                if not head or not tail:
                    continue

                # Discover head entity
                head_node = await self.discover_node(
                    label=LABEL_FACT,
                    name=head.lower(),
                    properties={
                        "canonical_name": head,
                        "source": step_description,
                        "extraction_method": "llm",
                    },
                    session_id=session_id,
                    confidence=confidence,
                )

                # Discover tail entity
                tail_node = await self.discover_node(
                    label=LABEL_FACT,
                    name=tail.lower(),
                    properties={
                        "canonical_name": tail,
                        "source": step_description,
                        "extraction_method": "llm",
                    },
                    session_id=session_id,
                    confidence=confidence,
                )

                # Create the relationship edge
                await self.relate_nodes(
                    source_id=head_node.id,
                    target_id=tail_node.id,
                    relation=relation,
                    confidence=confidence,
                    evidence=f"LLM extracted from: {step_description[:200]}",
                )
                count += 1

            if count:
                logger.info("LLM extraction stored %d triplets", count)
            return count

        except Exception:
            logger.warning("LLM extraction failed (non-fatal)", exc_info=True)
            return 0

    async def query(self, label: str | None = None, **filters: Any) -> list[KnowledgeNode]:
        """Query knowledge nodes.

        Args:
            label: Optional label filter.
            **filters: Property key-value filters.

        Returns:
            List of matching KnowledgeNode instances.
        """
        return await self._adapter.query(label=label, filters=filters or None)

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
        """Multi-mode search fusing sparse (FTS5), dense (cosine), and structured results.

        Delegates to the adapter which performs the fan-out and fusion.

        Args:
            query: Free-text search query.
            label: Optional node label filter.
            filters: Optional property key-value filters.
            limit: Max results.
            dense_weight: Weight for dense leg in RRF.
            sparse_weight: Weight for sparse leg in RRF.
            structured_weight: Weight for structured leg in RRF.

        Returns:
            List of ScoredNode sorted by fused relevance.
        """
        return await self._adapter.hybrid_search(
            query,
            label=label,
            filters=filters,
            limit=limit,
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
            structured_weight=structured_weight,
        )

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
