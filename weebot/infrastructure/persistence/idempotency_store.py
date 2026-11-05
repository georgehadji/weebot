"""SQLiteIdempotencyStore -- IdempotencyPort over the ``api_idempotency`` table (H12b).

Schema is also in alembic (``a1d3mp0t3nc1_api_idempotency``); like the other stores this one
creates its own table, because the CLI never runs alembic.
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weebot.application.ports.idempotency_port import IdempotencyPort

TTL = timedelta(hours=24)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_idempotency (
    key TEXT NOT NULL,
    principal TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (key, principal)
)
"""


class SQLiteIdempotencyStore(IdempotencyPort):
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute(_SCHEMA)
        return conn

    def _get(self, key: str, principal: str) -> str | None:
        cutoff = (datetime.now(UTC) - TTL).isoformat()
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM api_idempotency WHERE created_at < ?", (cutoff,))
            row = conn.execute(
                "SELECT run_id FROM api_idempotency WHERE key = ? AND principal = ?",
                (key, principal),
            ).fetchone()
        return row[0] if row else None

    def _put(self, key: str, principal: str, run_id: str) -> str:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO api_idempotency VALUES (?, ?, ?, ?)",
                (key, principal, run_id, datetime.now(UTC).isoformat()),
            )
            row = conn.execute(
                "SELECT run_id FROM api_idempotency WHERE key = ? AND principal = ?",
                (key, principal),
            ).fetchone()
        return row[0]

    def _forget(self, key: str, principal: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "DELETE FROM api_idempotency WHERE key = ? AND principal = ?", (key, principal)
            )

    async def forget(self, key: str, principal: str) -> None:
        await asyncio.to_thread(self._forget, key, principal)

    async def get(self, key: str, principal: str) -> str | None:
        return await asyncio.to_thread(self._get, key, principal)

    async def put(self, key: str, principal: str, run_id: str) -> str:
        return await asyncio.to_thread(self._put, key, principal, run_id)
