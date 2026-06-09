"""SkillVariantStore — SQLite adapter for skill variant persistence.

Implements SkillVariantStorePort using weebot's existing SQLite infrastructure.
Supports insert, domain-scoped queries, score updates, and children counting.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from weebot.application.ports.skill_variant_store_port import SkillVariantStorePort
from weebot.domain.models.skill_variant import SkillVariant

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("skill_variants.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS skill_variants (
    variant_id   TEXT PRIMARY KEY,
    parent_id    TEXT,
    skill_name   TEXT NOT NULL,
    skill_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    score        REAL NOT NULL DEFAULT 0.0,
    domain       TEXT NOT NULL DEFAULT '',
    generation   INTEGER NOT NULL DEFAULT 0,
    children_count INTEGER NOT NULL DEFAULT 0,
    meta_notes   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sv_domain_score
    ON skill_variants(domain, score DESC);

CREATE INDEX IF NOT EXISTS idx_sv_parent
    ON skill_variants(parent_id);
"""


class SkillVariantStore(SkillVariantStorePort):
    """SQLite-backed skill variant archive."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_SCHEMA_SQL)

    async def insert(self, variant: SkillVariant) -> str:
        """Persist a variant. Auto-generates UUID if variant_id is empty."""
        vid = variant.variant_id or str(uuid.uuid4())
        variant.variant_id = vid

        def _insert() -> str:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO skill_variants
                       (variant_id, parent_id, skill_name, skill_content,
                        content_hash, score, domain, generation,
                        children_count, meta_notes, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        vid, variant.parent_id, variant.skill_name,
                        variant.skill_content, variant.content_hash,
                        variant.score, variant.domain, variant.generation,
                        variant.children_count, variant.meta_notes,
                        variant.created_at.isoformat(),
                    ),
                )
            return vid

        import asyncio
        return await asyncio.to_thread(_insert)

    async def get_by_domain(
        self, domain: str, limit: int = 50
    ) -> list[SkillVariant]:
        def _query() -> list[dict]:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM skill_variants WHERE domain = ? "
                    "ORDER BY score DESC LIMIT ?",
                    (domain, limit),
                ).fetchall()
            return [dict(r) for r in rows]

        import asyncio
        rows = await asyncio.to_thread(_query)
        return [SkillVariant(**self._row_to_kwargs(r)) for r in rows]

    async def get_by_id(self, variant_id: str) -> Optional[SkillVariant]:
        def _query() -> dict | None:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM skill_variants WHERE variant_id = ?",
                    (variant_id,),
                ).fetchone()
            return dict(row) if row else None

        import asyncio
        row = await asyncio.to_thread(_query)
        return SkillVariant(**self._row_to_kwargs(row)) if row else None

    async def update_score(self, variant_id: str, score: float) -> None:
        def _update() -> None:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "UPDATE skill_variants SET score = ? WHERE variant_id = ?",
                    (score, variant_id),
                )

        import asyncio
        await asyncio.to_thread(_update)

    async def increment_children(self, variant_id: str) -> None:
        def _update() -> None:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "UPDATE skill_variants SET children_count = children_count + 1 "
                    "WHERE variant_id = ?",
                    (variant_id,),
                )

        import asyncio
        await asyncio.to_thread(_update)

    async def get_parent_candidates(
        self, domain: str, top_k: int = 10
    ) -> list[SkillVariant]:
        """Return top variants ordered by novelty-biased composite score.

        Formula: score × (1 / (1 + children_count))
        Higher scores and fewer children = better parent candidate.
        """
        def _query() -> list[dict]:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT * FROM skill_variants
                       WHERE domain = ?
                       ORDER BY score * (1.0 / (1.0 + children_count)) DESC
                       LIMIT ?""",
                    (domain, top_k),
                ).fetchall()
            return [dict(r) for r in rows]

        import asyncio
        rows = await asyncio.to_thread(_query)
        return [SkillVariant(**self._row_to_kwargs(r)) for r in rows]

    @staticmethod
    def _row_to_kwargs(row: dict) -> dict:
        """Convert a flat DB row to SkillVariant constructor kwargs."""
        return {k: row.get(k, None) for k in SkillVariant.model_fields}
