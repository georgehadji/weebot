"""Port: search what past sessions did (H15).

The `search_history` tool depends on this and nothing in the infrastructure layer.
`discover` finds sessions, `scroll` reads the events around one hit, `read` returns one
event. The SQLite adapter is `infrastructure/persistence/session_search_sqlite.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

# "text": the query is words, operators are quoted away. "fts": FTS5 syntax passes through
# (AND/OR/NOT, NEAR, "phrase", prefix*, column: filters) after it is checked.
SearchSyntax = Literal["text", "fts"]


class SessionSearchError(ValueError):
    """The query is not valid for the chosen syntax."""


class SessionSearchPort(ABC):
    @abstractmethod
    async def discover(
        self, query: str, limit: int = 10, syntax: SearchSyntax = "text"
    ) -> list[dict[str, Any]]:
        """Sessions that match, best first: one row per session with its best event.

        Each row has ``session_id``, ``event_id``, ``ts``, ``event_type``, ``summary``,
        ``content``, ``score`` (0 to 1, higher is better) and ``hits`` (matching events).
        """

    @abstractmethod
    async def scroll(
        self, session_id: str, around_event_id: str, window: int = 5
    ) -> list[dict[str, Any]]:
        """Up to ``window`` events before and after one event, in order, the event included."""

    @abstractmethod
    async def read(self, event_id: str) -> dict[str, Any] | None:
        """One indexed event, or None."""
