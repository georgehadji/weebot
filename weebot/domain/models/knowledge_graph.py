"""Knowledge graph domain models — entities, relationships, and temporal snapshots.

Three model types:
- KnowledgeNode:  A discrete entity (competitor, person, technology, file, fact)
- KnowledgeEdge:  A typed relationship between two nodes
- KnowledgeSnapshot: Temporal record of what changed about a node

Reserved property keys (stored in the ``properties`` JSON dict):
    - ``_confidence``: Float 0.0–1.0
    - ``_valid_from``: ISO-8601 timestamp of when this value became current
    - ``_valid_to``: ISO-8601 timestamp of when this value was superseded
    - ``_corroboration_count``: Integer, incremented when matching facts
      arrive without conflict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Reserved property keys ──────────────────────────────────────────
# Stored inside the ``properties`` JSON dict, not as top-level columns.
# No schema migration needed.

CONFIDENCE_KEY = "_confidence"
"""Confidence score for this fact (0.0–1.0)."""

VALID_FROM_KEY = "_valid_from"
"""ISO-8601 timestamp of when this fact became current.

Set when a new observation supersedes a prior one via recency tiebreak.
"""

VALID_TO_KEY = "_valid_to"
"""ISO-8601 timestamp of when this fact was superseded.

Stamped on the old value when it is replaced by a more recent observation.
Absent (None) = currently active.
"""

CORROBORATION_KEY = "_corroboration_count"
"""Integer count of how many times this fact has been corroborated.

Incremented when an incoming observation agrees with the stored value
(e.g. same key+value or negligible delta).
"""


class KnowledgeNode(BaseModel):
    """A discrete entity in the knowledge graph."""
    id: str = Field(default="", description="Unique node identifier")
    label: str = Field(default="fact", description="Node type: competitor, person, technology, file, fact")
    name: str = Field(default="", description="Human-readable entity name")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value properties (price, url, confidence, etc.)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this node was first discovered",
    )
    source_session_id: str = Field(default="", description="Which session discovered this node")
    version: int = Field(default=1, description="Monotonic version counter")


class KnowledgeEdge(BaseModel):
    """A typed relationship between two knowledge graph nodes."""
    source_id: str = Field(default="", description="Source node ID")
    target_id: str = Field(default="", description="Target node ID")
    relation: str = Field(
        default="",
        description="Relationship type: competes_with, uses, priced_at, authored_by, etc.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence in this relationship")
    evidence: str = Field(
        default="",
        description="Citation or tool call that established this edge",
    )


class ScoredNode(BaseModel):
    """A knowledge graph node with a relevance score from hybrid search."""
    node: Optional[KnowledgeNode] = Field(default=None, description="The matched node (None when only scores are computed)")
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Fused relevance score")
    sparse_score: float = Field(default=0.0, ge=0.0, le=1.0, description="FTS5 BM25 component")
    dense_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Cosine similarity component")
    structured_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Label/filter component")


class KnowledgeSnapshot(BaseModel):
    """Temporal record of changes to a knowledge graph node."""
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the snapshot was taken",
    )
    node_id: str = Field(default="", description="The node that changed")
    previous_properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Properties before the change",
    )
    new_properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Properties after the change",
    )
