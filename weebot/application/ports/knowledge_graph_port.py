"""Knowledge Graph port — abstract interface for entity and relationship storage."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from weebot.domain.models.knowledge_graph import KnowledgeEdge, KnowledgeNode, KnowledgeSnapshot


class KnowledgeGraphPort(ABC):
    """Interface for the knowledge graph storage and query layer."""

    @abstractmethod
    async def upsert_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Insert or update a knowledge graph node.

        If a node with the same label+name exists, properties are merged
        (new values overwrite old) and the version is incremented.

        Args:
            node: The node to insert or update.

        Returns:
            The updated node (with id and version populated).
        """
        ...

    @abstractmethod
    async def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        """Add a typed relationship between two nodes.

        Args:
            edge: The edge to add.

        Returns:
            The stored edge.
        """
        ...

    @abstractmethod
    async def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Fetch a single node by its unique ID.

        Args:
            node_id: The node's primary key.

        Returns:
            KnowledgeNode if found, None otherwise.
        """
        ...

    @abstractmethod
    async def query(
        self, label: Optional[str] = None, filters: Optional[dict[str, Any]] = None
    ) -> list[KnowledgeNode]:
        """Query nodes by label and optional property filters.

        Args:
            label: Optional node label to filter by.
            filters: Optional property key-value pairs to match.

        Returns:
            List of matching KnowledgeNode instances.
        """
        ...

    @abstractmethod
    async def get_neighbors(
        self, node_id: str, depth: int = 1
    ) -> dict[str, list[dict[str, Any]]]:
        """Get neighboring nodes and edges for a given node.

        Args:
            node_id: The node to find neighbors of.
            depth: How many hops to traverse (default 1).

        Returns:
            Dict with 'nodes' and 'edges' lists.
        """
        ...

    @abstractmethod
    async def snapshot(self, node_id: str) -> Optional[KnowledgeSnapshot]:
        """Get the most recent snapshot of a node's properties.

        Args:
            node_id: The node to snapshot.

        Returns:
            KnowledgeSnapshot if the node exists, None otherwise.
        """
        ...

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[KnowledgeNode]:
        """Full-text search across node names and properties.

        Args:
            query: Search string.
            limit: Max results to return.

        Returns:
            List of matching KnowledgeNode instances.
        """
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get summary statistics about the knowledge graph.

        Returns:
            Dict with node_count, edge_count, oldest_node, newest_node, etc.
        """
        ...
