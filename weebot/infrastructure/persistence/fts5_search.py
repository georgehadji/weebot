"""FTS5 event search — full-text search over session events.

Adds an FTS5 virtual table to the existing SQLite session database,
indexing event summaries, plan titles, and tool outputs.  Enables
semantic search over the agent's entire history.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FTS5_CREATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
    session_id UNINDEXED,
    event_type,
    summary,
    content,
    tokenize='porter unicode61'
)
"""

_FTS5_INSERT = """
INSERT INTO event_fts(session_id, event_type, summary, content)
VALUES (?, ?, ?, ?)
"""

_FTS5_SEARCH = """
SELECT session_id, event_type, summary, content, rank
FROM event_fts
WHERE event_fts MATCH ?
ORDER BY rank
LIMIT ?
"""

_FTS5_DELETE_SESSION = """
DELETE FROM event_fts WHERE session_id = ?
"""


async def ensure_fts5_table(conn) -> None:
    """Create the FTS5 virtual table if it doesn't exist."""
    await conn.execute(_FTS5_CREATE)
    logger.debug("FTS5 event search table ensured")


async def index_event(
    conn,
    session_id: str,
    event_type: str,
    summary: str,
    content: str = "",
) -> None:
    """Index a single event into the FTS5 table.

    Call this after saving a new event to the sessions table.
    """
    await conn.execute(
        _FTS5_INSERT,
        (session_id, event_type, summary[:500], content[:1000]),
    )


async def search_events(
    pool,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Full-text search across all indexed events.

    Args:
        pool: SQLiteConnectionPool instance.
        query: FTS5 search query (porter-tokenized).
        limit: Max results.

    Returns:
        List of {session_id, event_type, summary, content, score}.
    """
    rows = await pool.execute_read(_FTS5_SEARCH, (query, limit))
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
    """Remove all FTS5 entries for a deleted session."""
    await conn.execute(_FTS5_DELETE_SESSION, (session_id,))