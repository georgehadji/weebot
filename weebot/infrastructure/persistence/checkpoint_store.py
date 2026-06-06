"""SQLiteCheckpointStore — persists FlowCheckpoints to SQLite.

Implements :class:`~weebot.application.ports.checkpoint_port.CheckpointPort`
using SQLite with WAL mode for concurrent-safe writes.  Only the latest
checkpoint per session is retained.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from weebot.application.ports.checkpoint_port import CheckpointPort
from weebot.domain.models.checkpoint import FlowCheckpoint

_log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS flow_checkpoints (
    session_id   TEXT PRIMARY KEY,
    flow_type    TEXT NOT NULL DEFAULT 'PlanActFlow',
    current_state TEXT NOT NULL DEFAULT 'planning',
    checkpoint_json TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class SQLiteCheckpointStore(CheckpointPort):
    """SQLite-backed checkpoint store.

    Args:
        db_path: Path to the SQLite database file (shared with other stores
                 like sessions.db).

    Example:
        store = SQLiteCheckpointStore("sessions.db")
        await store.save(checkpoint)
        restored = await store.load("session-123")
    """

    def __init__(self, db_path: str = "sessions.db") -> None:
        self._db_path = Path(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the checkpoints table if it doesn't exist."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_DDL)
            conn.commit()

    # ── CheckpointPort implementation ─────────────────────────────────

    async def save(self, checkpoint: FlowCheckpoint) -> None:
        """Persist a checkpoint (upsert — last-write-wins)."""
        json_blob = checkpoint.model_dump_json()
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """INSERT INTO flow_checkpoints (session_id, flow_type, current_state, checkpoint_json, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(session_id) DO UPDATE SET
                     flow_type = excluded.flow_type,
                     current_state = excluded.current_state,
                     checkpoint_json = excluded.checkpoint_json,
                     updated_at = datetime('now')""",
                (checkpoint.session_id, checkpoint.flow_type, checkpoint.current_state, json_blob),
            )
            conn.commit()

    async def load(self, session_id: str) -> FlowCheckpoint | None:
        """Load the checkpoint for a session, or None."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT checkpoint_json FROM flow_checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return FlowCheckpoint.model_validate_json(row["checkpoint_json"])
        except Exception:
            _log.exception("Failed to deserialize checkpoint for %s", session_id)
            return None

    async def delete(self, session_id: str) -> bool:
        """Delete a checkpoint. Returns True if one was deleted."""
        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM flow_checkpoints WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    async def list_checkpointed_sessions(self) -> list[str]:
        """Return session IDs with saved checkpoints."""
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id FROM flow_checkpoints ORDER BY updated_at DESC",
            ).fetchall()
        return [r[0] for r in rows]
