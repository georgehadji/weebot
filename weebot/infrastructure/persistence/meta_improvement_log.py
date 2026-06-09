"""MetaImprovementLog — append-only audit trail for meta-level self-edits.

Implements Enhancement 7 from the HyperAgents plan: when the SelfImprover
edits its own prompt or configuration (metacognitive self-improvement),
every edit is logged to an append-only SQLite log.  This provides
traceability and rollback capability.

The log is append-only by design — no UPDATE or DELETE operations exist.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path("meta_improvement_log.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta_edits (
    edit_id        TEXT PRIMARY KEY,
    timestamp      TEXT NOT NULL,
    editor         TEXT NOT NULL,
    target_file    TEXT NOT NULL,
    change_summary TEXT NOT NULL,
    previous_hash  TEXT,
    new_hash       TEXT,
    rollback_info  TEXT
);

CREATE INDEX IF NOT EXISTS idx_me_timestamp
    ON meta_edits(timestamp DESC);
"""


class MetaImprovementLog:
    """Append-only audit log for metacognitive self-improvements.

    Usage:
        log = MetaImprovementLog()
        await log.record(
            editor="MetaSelfImprover",
            target_file="self_improver.py:allowlist",
            change_summary="Added config/prompts/variants to allowed targets",
            previous_hash="abc123",
            new_hash="def456",
        )
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_LOG_PATH
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_SCHEMA_SQL)

    async def record(
        self,
        editor: str,
        target_file: str,
        change_summary: str,
        previous_hash: str | None = None,
        new_hash: str | None = None,
        rollback_info: str | None = None,
    ) -> str:
        """Record a meta-edit to the audit log.

        Returns the edit_id for reference.
        """
        edit_id = str(uuid.uuid4())

        def _insert() -> str:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """INSERT INTO meta_edits
                       (edit_id, timestamp, editor, target_file,
                        change_summary, previous_hash, new_hash, rollback_info)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        edit_id,
                        datetime.now(timezone.utc).isoformat(),
                        editor,
                        target_file,
                        change_summary,
                        previous_hash,
                        new_hash,
                        rollback_info,
                    ),
                )
            return edit_id

        result = await asyncio.to_thread(_insert)
        logger.info("Meta-edit recorded: %s → %s", editor, change_summary[:100])
        return result

    async def get_recent(self, limit: int = 20) -> list[dict]:
        """Return the most recent meta-edits."""
        def _query() -> list[dict]:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM meta_edits ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

        return await asyncio.to_thread(_query)
