"""FTS5 event search — full-text search over session events.

Adds FTS5 virtual tables to the existing SQLite session database, indexing event
summaries, plan titles, and tool outputs.  Enables semantic search over the agent's
entire history.

Two tables hold the same rows (H15): ``event_fts`` (porter + unicode61, word search)
and ``event_fts_trigram`` (substring and non-Latin search, tool results left out).
``fts_watermark`` records how far each session is indexed, so a restart does not index
it again.  The queries that read these tables live in ``session_search_sqlite``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _sanitize_fts_query(q: str) -> str:
    """Sanitize an FTS5 query to neutralize operators while preserving literal match.

    Wraps each whitespace-separated token in double quotes (escaping any
    embedded double quotes by doubling them), which neutralises FTS5 operators
    (NEAR, AND/OR, column filters, ``*``) and returns a literal-token query.

    Args:
        q: Raw user-supplied query string.

    Returns:
        Sanitized query safe for FTS5 MATCH.
    """
    tokens = q.strip().split()
    if not tokens:
        return ""
    quoted = []
    for token in tokens:
        # Escape embedded double quotes by doubling them (FTS5 convention)
        safe = token.replace('"', '""')
        quoted.append(f'"{safe}"')
    return " AND ".join(quoted)


_FTS5_COLUMNS = (
    "session_id UNINDEXED, event_id UNINDEXED, ts UNINDEXED, event_type, summary, content"
)

_FTS5_CREATE = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
    {_FTS5_COLUMNS},
    tokenize='porter unicode61'
)
"""

_FTS5_TRIGRAM_CREATE = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts_trigram USING fts5(
    {_FTS5_COLUMNS},
    tokenize='trigram'
)
"""

_FTS_WATERMARK_CREATE = """
CREATE TABLE IF NOT EXISTS fts_watermark (
    session_id TEXT PRIMARY KEY,
    last_event_idx INTEGER NOT NULL
)
"""

_FTS5_INSERT = """
INSERT INTO event_fts(session_id, event_id, ts, event_type, summary, content)
VALUES (?, ?, ?, ?, ?, ?)
"""

_FTS5_TRIGRAM_INSERT = _FTS5_INSERT.replace("event_fts(", "event_fts_trigram(")

_FTS5_SEARCH = """
SELECT session_id, event_type, summary, content, rank
FROM event_fts
WHERE event_fts MATCH ?
ORDER BY rank
LIMIT ?
"""

_TRIGRAM_MIN_SQLITE = (3, 34, 0)

# Set by `ensure_fts5_table`: whether this SQLite build has the trigram tokenizer.
trigram_available = False

# Tool results are large and rarely searched by substring: they stay out of the trigram table.
_TRIGRAM_SKIPPED_TYPES = frozenset({"tool"})


async def _event_fts_has_ids(conn) -> bool:
    cursor = await conn.execute("PRAGMA table_info(event_fts)")
    return "event_id" in {row[1] for row in await cursor.fetchall()}


async def ensure_fts5_table(conn) -> None:
    """Create the FTS5 tables and the watermark table if they don't exist.

    Both FTS tables are derived data. A table from before event ids and timestamps is
    dropped with its watermarks and rebuilt lazily: each session re-indexes on its next
    save.
    """
    global trigram_available
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE name = 'event_fts'")
    if await cursor.fetchone() and not await _event_fts_has_ids(conn):
        logger.info("Rebuilding event_fts with event ids; sessions re-index on their next save")
        await conn.execute("DROP TABLE event_fts")
        await conn.execute("DROP TABLE IF EXISTS fts_watermark")
    await conn.execute(_FTS5_CREATE)
    await conn.execute(_FTS_WATERMARK_CREATE)
    cursor = await conn.execute("SELECT sqlite_version()")
    version = tuple(int(part) for part in (await cursor.fetchone())[0].split(".")[:3])
    trigram_available = version >= _TRIGRAM_MIN_SQLITE
    if trigram_available:
        await conn.execute(_FTS5_TRIGRAM_CREATE)
    else:
        logger.warning(
            "SQLite %s has no trigram tokenizer (needs 3.34); substring search is off",
            ".".join(map(str, version)),
        )
    logger.debug("FTS5 event search tables ensured")


async def index_event(
    conn,
    session_id: str,
    event_type: str,
    summary: str,
    content: str = "",
    event_id: str = "",
    ts: str = "",
) -> None:
    """Index a single event into the FTS5 tables.

    Call this after saving a new event to the sessions table.
    """
    row = (session_id, event_id, ts, event_type, summary[:500], content[:1000])
    await conn.execute(_FTS5_INSERT, row)
    if trigram_available and event_type not in _TRIGRAM_SKIPPED_TYPES:
        await conn.execute(_FTS5_TRIGRAM_INSERT, row)


async def load_watermark(pool, session_id: str) -> int | None:
    """How many events of the session are indexed, or None when it never was."""
    rows = await pool.execute_read(
        "SELECT last_event_idx FROM fts_watermark WHERE session_id = ?", (session_id,)
    )
    return rows[0]["last_event_idx"] if rows else None


async def save_watermark(conn, session_id: str, last_event_idx: int) -> None:
    await conn.execute(
        "INSERT INTO fts_watermark(session_id, last_event_idx) VALUES (?, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET last_event_idx = excluded.last_event_idx",
        (session_id, last_event_idx),
    )


async def search_events(pool, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Full-text search across all indexed events.

    Args:
        pool: SQLiteConnectionPool instance.
        query: FTS5 search query (porter-tokenized).
        limit: Max results.

    Returns:
        List of {session_id, event_type, summary, content, score}.
    """
    rows = await pool.execute_read(_FTS5_SEARCH, (_sanitize_fts_query(query), limit))
    return [
        {
            "session_id": r["session_id"],
            "event_type": r["event_type"],
            "summary": r["summary"],
            "content": r["content"],
            "score": round(1.0 / (1.0 + r["rank"]), 4) if r["rank"] is not None else 0.0,
        }
        for r in rows
    ]


async def clear_session_events(conn, session_id: str) -> None:
    """Remove all FTS5 entries and the watermark of a deleted session."""
    await conn.execute("DELETE FROM event_fts WHERE session_id = ?", (session_id,))
    if trigram_available:
        await conn.execute("DELETE FROM event_fts_trigram WHERE session_id = ?", (session_id,))
    await conn.execute("DELETE FROM fts_watermark WHERE session_id = ?", (session_id,))
