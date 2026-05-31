"""SQLite-based summary repository with lightweight in-memory vector search."""
from __future__ import annotations

import json
import math
import sqlite3
from typing import List, Tuple

from weebot.application.ports.summary_repo_port import SummaryRepositoryPort


class SQLiteSummaryRepository(SummaryRepositoryPort):
    """Stores session summaries in SQLite and performs cosine similarity in Python."""

    def __init__(self, db_path: str = "./weebot_summaries.db") -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    embedding_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    async def save_summary(
        self,
        session_id: str,
        summary: str,
        embedding: List[float],
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO summaries (session_id, summary, embedding_json) VALUES (?, ?, ?)",
                (session_id, summary, json.dumps(embedding)),
            )
            conn.commit()

    async def find_similar(
        self,
        embedding: List[float],
        k: int = 3,
    ) -> List[Tuple[str, str, float]]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT session_id, summary, embedding_json FROM summaries"
            ).fetchall()

        results: List[Tuple[str, str, float]] = []
        query_norm = _norm(embedding)
        for session_id, summary, emb_json in rows:
            candidate = json.loads(emb_json)
            score = _cosine_similarity(embedding, candidate, query_norm)
            results.append((session_id, summary, score))

        results.sort(key=lambda x: x[2], reverse=True)
        return results[:k]


def _norm(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _cosine_similarity(a: List[float], b: List[float], norm_a: float | None = None) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_b = _norm(b)
    if norm_a is None:
        norm_a = _norm(a)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
