"""Knowledge graph domain models — entities, relationships, and temporal snapshots.

Three model types:
- KnowledgeNode:  A discrete entity (competitor, person, technology, file, fact)
- KnowledgeEdge:  A typed relationship between two nodes
- KnowledgeSnapshot: Temporal record of what changed about a node
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


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
