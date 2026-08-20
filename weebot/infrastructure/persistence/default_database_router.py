"""Default DatabaseRouter — single-file SQLite for all entity types.

Phase C1 transitional implementation: all entities map to the same
``weebot_sessions.db``.  When the DB split is activated, each entity
type will get its own file (e.g. ``weebot_memory.db``).
"""

from __future__ import annotations

from pathlib import Path

from weebot.application.ports.database_router_port import DatabaseRouterPort


class DefaultDatabaseRouter(DatabaseRouterPort):
    """Maps all entity types to a single SQLite database.

    Used as the default/transitional implementation.  Swap to
    ``SplitDatabaseRouter`` when the DB split is activated.
    """

    def __init__(self, db_path: str | Path = "./weebot_sessions.db"):
        self._default_path = Path(db_path).resolve()
        self._overrides: dict[str, Path] = {}

    def get_db_path(self, entity_type: str) -> Path:
        if entity_type in self._overrides:
            return self._overrides[entity_type]
        return self._default_path

    def list_entity_types(self) -> list[str]:
        return list(self._overrides.keys())

    def register(self, entity_type: str, db_path: str | Path) -> None:
        self._overrides[entity_type] = Path(db_path).resolve()
