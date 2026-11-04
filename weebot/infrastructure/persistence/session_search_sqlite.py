"""SQLite implementation of SessionSearchPort over the FTS5 tables (H15).

Two indexes answer one query. Word search uses `event_fts` (porter + unicode61).
Substring and non-Latin search uses `event_fts_trigram`, so "onfig" finds "config" and a
Greek or CJK query finds its text. `plan_query` decides which index gets which words; it is
pure, so it is tested without a database.
"""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from weebot.application.ports.session_search_port import (
    SearchSyntax,
    SessionSearchError,
    SessionSearchPort,
)
from weebot.infrastructure.persistence import fts5_search
from weebot.infrastructure.persistence.connection_pool import get_or_create_pool

logger = logging.getLogger(__name__)

_COLUMNS = "session_id, event_id, ts, event_type, summary, content"
_MAX_SCROLL_WINDOW = 50
_MAX_ROWS_PER_QUERY = 500
_TRIGRAM_MIN_CHARS = 3


@dataclass(frozen=True)
class QueryPlan:
    """The MATCH expression for each index; an empty string means "do not query it"."""

    word: str = ""
    substring: str = ""


def _quote(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _is_latin(token: str) -> bool:
    letters = [c for c in token if c.isalpha()]
    return all(unicodedata.name(c, "").startswith("LATIN") for c in letters)


def plan_query(query: str, syntax: SearchSyntax = "text") -> QueryPlan:
    """Split a query between the word index and the substring index.

    ``fts`` syntax goes to the word index as written; the trigram table has no stemmer, so
    operators there would mean something different. For ``text``, every Latin token is a
    word (short ones too: unicode61 handles "go"), and every token of three characters or
    more is also a substring. A non-Latin token is only a substring. The trigram tokenizer
    cannot match fewer than three characters, so a one- or two-character CJK word finds
    nothing (shortcut: no LIKE fallback, add one if short CJK queries matter).
    """
    if syntax == "fts":
        return QueryPlan(word=query.strip())
    tokens = query.split()
    return QueryPlan(
        word=" AND ".join(_quote(t) for t in tokens if _is_latin(t)),
        substring=" AND ".join(_quote(t) for t in tokens if len(t) >= _TRIGRAM_MIN_CHARS),
    )


def _score(rank: float | None) -> float:
    """bm25 `rank` is negative and lower is better; 0 to 1, higher is better."""
    quality = max(0.0, -(rank or 0.0))
    return round(quality / (1.0 + quality), 4)


class SqliteSessionSearch(SessionSearchPort):
    def __init__(self, get_pool: Callable[[], Awaitable[Any]]) -> None:
        self._get_pool = get_pool

    @classmethod
    def at(cls, db_path: str | Path) -> SqliteSessionSearch:
        """Search the session database at a path, opening its pool on first use."""

        async def pool():
            return await get_or_create_pool(Path(db_path), max_read_connections=3, enable_wal=True)

        return cls(pool)

    async def _matches(self, table: str, expression: str, cap: int, syntax: str) -> list[Any]:
        pool = await self._get_pool()
        sql = f"SELECT {_COLUMNS}, rank FROM {table} WHERE {table} MATCH ? ORDER BY rank LIMIT ?"
        try:
            return list(await pool.execute_read(sql, (expression, cap)))
        except sqlite3.Error as exc:
            if syntax == "fts":
                raise SessionSearchError(f"invalid FTS5 query {expression!r}: {exc}") from exc
            raise

    async def discover(
        self, query: str, limit: int = 10, syntax: SearchSyntax = "text"
    ) -> list[dict[str, Any]]:
        plan = plan_query(query, syntax)
        cap = min(max(limit, 1) * 10, _MAX_ROWS_PER_QUERY)
        rows: list[Any] = []
        if plan.word:
            rows += await self._matches("event_fts", plan.word, cap, syntax)
        if plan.substring and fts5_search.trigram_available:
            rows += await self._matches("event_fts_trigram", plan.substring, cap, syntax)

        # One row per event, its best score, then one row per session, its best event.
        best: dict[tuple[str, str], tuple[float, Any]] = {}
        for row in rows:
            key = (row["session_id"], row["event_id"] or f"{row['ts']}|{row['summary']}")
            score = _score(row["rank"])
            if key not in best or score > best[key][0]:
                best[key] = (score, row)
        sessions: dict[str, dict[str, Any]] = {}
        for (session_id, _), (score, row) in best.items():
            found = sessions.get(session_id)
            if found is None:
                sessions[session_id] = {**self._event(row), "score": score, "hits": 1}
                continue
            found["hits"] += 1
            if score > found["score"]:
                found.update(self._event(row), score=score)
        ranked = sorted(sessions.values(), key=lambda s: (-s["score"], -s["hits"]))
        return ranked[: max(limit, 1)]

    async def scroll(
        self, session_id: str, around_event_id: str, window: int = 5
    ) -> list[dict[str, Any]]:
        window = max(0, min(window, _MAX_SCROLL_WINDOW))
        pool = await self._get_pool()
        target = await pool.execute_read(
            f"SELECT rowid AS pos, {_COLUMNS} FROM event_fts WHERE session_id = ? AND event_id = ?",
            (session_id, around_event_id),
        )
        if not target:
            return []
        pos = target[0]["pos"]
        before = await pool.execute_read(
            f"SELECT rowid AS pos, {_COLUMNS} FROM event_fts "
            "WHERE session_id = ? AND rowid < ? ORDER BY rowid DESC LIMIT ?",
            (session_id, pos, window),
        )
        after = await pool.execute_read(
            f"SELECT rowid AS pos, {_COLUMNS} FROM event_fts "
            "WHERE session_id = ? AND rowid > ? ORDER BY rowid ASC LIMIT ?",
            (session_id, pos, window),
        )
        ordered = [*reversed(before), target[0], *after]
        return [self._event(row) | {"target": row["pos"] == pos} for row in ordered]

    async def read(self, event_id: str) -> dict[str, Any] | None:
        pool = await self._get_pool()
        rows = await pool.execute_read(
            f"SELECT {_COLUMNS} FROM event_fts WHERE event_id = ? LIMIT 1", (event_id,)
        )
        return self._event(rows[0]) if rows else None

    @staticmethod
    def _event(row: Any) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "event_id": row["event_id"],
            "ts": row["ts"],
            "event_type": row["event_type"],
            "summary": row["summary"],
            "content": row["content"],
        }
