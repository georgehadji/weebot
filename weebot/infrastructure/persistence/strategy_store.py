"""StrategyStore — SQLite adapter for ImprovementStrategy persistence.

Implements Enhancement 6 from the HyperAgents plan: stores meta-level
improvement strategies for cross-domain transfer.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from weebot.domain.models.self_improvement import ImprovementStrategy

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("improvement_strategies.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS improvement_strategies (
    strategy_id          TEXT PRIMARY KEY,
    source_domain        TEXT NOT NULL,
    target_domain        TEXT,
    meta_agent_prompt_snippet TEXT NOT NULL,
    effectiveness_score  REAL NOT NULL DEFAULT 0.0,
    transfer_count       INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_is_source_domain
    ON improvement_strategies(source_domain);

CREATE INDEX IF NOT EXISTS idx_is_score
    ON improvement_strategies(effectiveness_score DESC);
"""


class StrategyStore:
    """SQLite-backed store for improvement strategies."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_SCHEMA_SQL)

    async def insert(self, strategy: ImprovementStrategy) -> str:
        sid = strategy.strategy_id or str(uuid.uuid4())
        strategy.strategy_id = sid

        def _insert() -> str:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO improvement_strategies
                       (strategy_id, source_domain, target_domain,
                        meta_agent_prompt_snippet, effectiveness_score,
                        transfer_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid, strategy.source_domain,
                        strategy.target_domain,
                        strategy.meta_agent_prompt_snippet,
                        strategy.effectiveness_score,
                        strategy.transfer_count,
                        strategy.created_at.isoformat(),
                    ),
                )
            return sid

        return await asyncio.to_thread(_insert)

    async def get_for_domain(
        self,
        target_domain: str,
        min_score: float = 0.7,
        limit: int = 5,
    ) -> list[ImprovementStrategy]:
        """Return strategies from DIFFERENT domains applicable to target_domain.

        Ordered by composite score: effectiveness_score × (1 + transfer_count).
        """
        def _query() -> list[dict]:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT * FROM improvement_strategies
                       WHERE source_domain != ?
                         AND effectiveness_score >= ?
                       ORDER BY effectiveness_score * (1.0 + transfer_count) DESC
                       LIMIT ?""",
                    (target_domain, min_score, limit),
                ).fetchall()
            return [dict(r) for r in rows]

        rows = await asyncio.to_thread(_query)
        return [
            ImprovementStrategy(
                strategy_id=r["strategy_id"],
                source_domain=r["source_domain"],
                target_domain=r.get("target_domain"),
                meta_agent_prompt_snippet=r["meta_agent_prompt_snippet"],
                effectiveness_score=r["effectiveness_score"],
                transfer_count=r["transfer_count"],
            )
            for r in rows
        ]

    async def increment_transfer(self, strategy_id: str) -> None:
        def _update() -> None:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "UPDATE improvement_strategies "
                    "SET transfer_count = transfer_count + 1 "
                    "WHERE strategy_id = ?",
                    (strategy_id,),
                )

        await asyncio.to_thread(_update)

    async def get_by_id(
        self, strategy_id: str
    ) -> Optional[ImprovementStrategy]:
        def _query() -> dict | None:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM improvement_strategies WHERE strategy_id = ?",
                    (strategy_id,),
                ).fetchone()
            return dict(row) if row else None

        row = await asyncio.to_thread(_query)
        if row is None:
            return None
        return ImprovementStrategy(
            strategy_id=row["strategy_id"],
            source_domain=row["source_domain"],
            target_domain=row.get("target_domain"),
            meta_agent_prompt_snippet=row["meta_agent_prompt_snippet"],
            effectiveness_score=row["effectiveness_score"],
            transfer_count=row["transfer_count"],
        )
