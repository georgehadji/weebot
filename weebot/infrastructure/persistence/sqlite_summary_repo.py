"""SQLite episodic-summary store with in-Python similarity search.

Similarity is cosine over local embeddings when both sides have one of the same
size, and token Jaccard (the plan-template cache's tokenizer) otherwise. Local
embeddings are an optional extra, so the fallback is what a default install uses.
The table is created on first write: a delete for a never-used store opens nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
from contextlib import closing
from pathlib import Path

from weebot.application.ports.summary_repo_port import SummaryRepositoryPort
from weebot.domain.services.plan_template_cache import jaccard_similarity, tokenize

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    summary TEXT NOT NULL,
    embedding_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


async def _embed(text: str) -> list[float] | None:
    """A local embedding of *text*, or None when the extra is not installed."""
    try:
        from weebot.qmd_integration.embeddings import get_local_embeddings

        emb = get_local_embeddings()
        if not emb.is_available():
            return None
        return list((await emb.embed_query(text)).embedding)
    except Exception:
        logger.debug("Summary embedding unavailable; token overlap is used", exc_info=True)
        return None


class SQLiteSummaryRepository(SummaryRepositoryPort):
    """Summaries of successful sessions, one row per session."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute(_SCHEMA)
        return conn

    async def save_summary(self, session_id: str, task: str, summary: str) -> None:
        embedding = await _embed(task) or []

        def _save() -> None:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT OR REPLACE INTO summaries (session_id, task, summary, embedding_json)"
                    " VALUES (?, ?, ?, ?)",
                    (session_id, task, summary, json.dumps(embedding)),
                )

        await asyncio.to_thread(_save)

    async def find_similar(self, task: str, k: int = 3) -> list[tuple[str, str, str, float]]:
        if not Path(self._db_path).exists():
            return []

        def _rows():
            with closing(self._connect()) as conn:
                return conn.execute(
                    "SELECT session_id, task, summary, embedding_json FROM summaries"
                ).fetchall()

        rows = await asyncio.to_thread(_rows)
        if not rows:
            return []
        query_vec = await _embed(task)
        query_tokens = tokenize(task)
        scored = []
        for session_id, past_task, summary, emb_json in rows:
            vec = json.loads(emb_json or "[]")
            if query_vec and vec and len(vec) == len(query_vec):
                score = _cosine(query_vec, vec)
            else:
                score = jaccard_similarity(query_tokens, tokenize(past_task))
            scored.append((session_id, past_task, summary, score))
        scored.sort(key=lambda row: row[3], reverse=True)
        return scored[:k]

    async def delete_by_session_id(self, session_id: str) -> int:
        if not Path(self._db_path).exists():
            return 0

        def _delete() -> int:
            with closing(self._connect()) as conn, conn:
                return conn.execute(
                    "DELETE FROM summaries WHERE session_id = ?", (session_id,)
                ).rowcount

        return await asyncio.to_thread(_delete)


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm
