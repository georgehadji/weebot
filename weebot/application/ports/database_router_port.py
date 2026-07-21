"""DatabaseRouter port — maps entity types to database paths.

Allows splitting a single monolithic database into domain-specific
databases without changing the call sites.  Each entity type maps to
a specific database path, and the router is the single source of truth
for those mappings.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class DatabaseRouterPort(ABC):
    """Maps entity types to database paths.

    Usage::

        router = container.get(DatabaseRouterPort)
        db_path = router.get_db_path("sessions")  # → Path(".../weebot_sessions.db")
        pool = await get_or_create_pool(db_path)
    """

    @abstractmethod
    def get_db_path(self, entity_type: str) -> Path:
        """Return the database path for *entity_type*.

        Args:
            entity_type: A domain entity name, e.g. ``"sessions"``,
                ``"memory"``, ``"rules"``, ``"events"``, ``"checkpoints"``.

        Returns:
            Absolute ``Path`` to the SQLite database file for that entity.

        Raises:
            KeyError: If *entity_type* is not a known entity.
        """
        ...

    @abstractmethod
    def list_entity_types(self) -> list[str]:
        """Return all known entity types."""
        ...

    @abstractmethod
    def register(self, entity_type: str, db_path: str | Path) -> None:
        """Register a custom mapping for *entity_type*.

        Args:
            entity_type: Domain entity name.
            db_path: Database file path for this entity.
        """
        ...
