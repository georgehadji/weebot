"""SQLiteCheckpointStore — persists FlowCheckpoints to SQLite.

Implements :class:`~weebot.application.ports.checkpoint_port.CheckpointPort`
using SQLite with WAL mode for concurrent-safe writes.  Only the latest
checkpoint per session is retained.

Schema managed by Alembic (migration c0re_5ch3m4_v1).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from weebot.application.ports.checkpoint_port import CheckpointPort
from weebot.domain.models.checkpoint import FlowCheckpoint

_log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_checkpoints (
    session_id TEXT PRIMARY KEY,
    flow_type TEXT NOT NULL,
    current_state TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
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

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open the store, creating its table. The CLI never runs alembic, so a
        table only alembic created (`flow_checkpoints`, same columns) was missing
        there; the store keeps its own file and makes its own table."""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(_SCHEMA)
        return conn

    # ── CheckpointPort implementation ─────────────────────────────────

    async def save(self, checkpoint: FlowCheckpoint) -> None:
        """Persist a checkpoint (upsert — last-write-wins).

        Offloads blocking SQLite I/O to the default thread-pool executor
        so the asyncio event loop is never blocked by disk writes.
        """
        json_blob = checkpoint.model_dump_json()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._save_sync,
            checkpoint.session_id,
            checkpoint.flow_type,
            checkpoint.current_state,
            json_blob,
        )

    def _save_sync(
        self, session_id: str, flow_type: str, current_state: str, json_blob: str
    ) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO flow_checkpoints (session_id, flow_type, current_state, checkpoint_json, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(session_id) DO UPDATE SET
                     flow_type = excluded.flow_type,
                     current_state = excluded.current_state,
                     checkpoint_json = excluded.checkpoint_json,
                     updated_at = datetime('now')""",
                (session_id, flow_type, current_state, json_blob),
            )
            conn.commit()

    async def load(self, session_id: str) -> FlowCheckpoint | None:
        """Load the checkpoint for a session, or None.

        Offloads blocking SQLite I/O to the default thread-pool executor.
        """
        loop = asyncio.get_running_loop()
        row_json = await loop.run_in_executor(None, self._load_sync, session_id)
        if row_json is None:
            return None
        try:
            return FlowCheckpoint.model_validate_json(row_json)
        except Exception:
            _log.exception("Failed to deserialize checkpoint for %s", session_id)
            return None

    def _load_sync(self, session_id: str) -> str | None:
        if not self._db_path.exists():
            return None
        with closing(self._connect()) as conn, conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT checkpoint_json FROM flow_checkpoints WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row["checkpoint_json"] if row else None

    async def delete(self, session_id: str) -> bool:
        """Delete a checkpoint. Returns True if one was deleted.

        Offloads blocking SQLite I/O to the default thread-pool executor.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._delete_sync, session_id)

    def _delete_sync(self, session_id: str) -> bool:
        if not self._db_path.exists():
            return False
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "DELETE FROM flow_checkpoints WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def list_checkpointed_sessions(self) -> list[str]:
        """Return session IDs with saved checkpoints.

        Offloads blocking SQLite I/O to the default thread-pool executor.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._list_sync)

    def _list_sync(self) -> list[str]:
        if not self._db_path.exists():
            return []
        with closing(self._connect()) as conn, conn:
            rows = conn.execute(
                "SELECT session_id FROM flow_checkpoints ORDER BY updated_at DESC"
            ).fetchall()
        return [r[0] for r in rows]
