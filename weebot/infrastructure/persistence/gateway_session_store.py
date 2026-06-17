"""SQLite-backed gateway session store.

Persists gateway sessions in a SQLite table so they survive process restarts.
Uses the existing connection pool from weebot.infrastructure.persistence when
available, or creates a standalone connection.

Schema:
    CREATE TABLE gateway_sessions (
        composite_key TEXT PRIMARY KEY,
        platform TEXT NOT NULL,
        chat_type TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        thread_id TEXT,
        flow_session_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_activity_at TEXT NOT NULL,
        title TEXT,
        user_id TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        metadata TEXT DEFAULT '{}'
    );
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weebot.application.ports.gateway_session_store_port import AbstractGatewaySessionStore
from weebot.domain.models.gateway_session import GatewaySession, GatewaySessionKey

logger = logging.getLogger(__name__)


class SQLiteGatewaySessionStore(AbstractGatewaySessionStore):
    """SQLite-backed persistence for gateway sessions."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else Path.home() / ".weebot" / "gateway_sessions.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new connection (not pooled — simple standalone store)."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gateway_sessions (
                    composite_key TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    chat_type TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT,
                    flow_session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_activity_at TEXT NOT NULL,
                    title TEXT,
                    user_id TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_gw_sessions_platform
                ON gateway_sessions(platform)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_gw_sessions_user
                ON gateway_sessions(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_gw_sessions_active
                ON gateway_sessions(is_active)
            """)
            conn.commit()

    def _row_to_session(self, row: sqlite3.Row) -> GatewaySession:
        """Convert a DB row to a GatewaySession model."""
        key = GatewaySessionKey(
            platform=row["platform"],
            chat_type=row["chat_type"],
            chat_id=row["chat_id"],
            thread_id=row.get("thread_id"),
        )
        metadata: dict[str, Any] = {}
        raw_meta = row["metadata"]
        if raw_meta:
            try:
                metadata = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

        return GatewaySession(
            key=key,
            flow_session_id=row["flow_session_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_activity_at=datetime.fromisoformat(row["last_activity_at"]),
            title=row.get("title"),
            user_id=row.get("user_id"),
            is_active=bool(row["is_active"]),
            metadata=metadata,
        )

    async def get(self, key: GatewaySessionKey) -> GatewaySession | None:
        """Retrieve a session by its composite key."""
        composite = key.composite_key()

        def _query() -> sqlite3.Row | None:
            with self._get_connection() as conn:
                return conn.execute(
                    "SELECT * FROM gateway_sessions WHERE composite_key = ?",
                    (composite,),
                ).fetchone()

        row = await asyncio.to_thread(_query)
        if row is None:
            return None
        return self._row_to_session(row)

    async def upsert(self, session: GatewaySession) -> None:
        """Create or update a session."""
        composite = session.key.composite_key()

        def _write() -> None:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO gateway_sessions
                       (composite_key, platform, chat_type, chat_id, thread_id,
                        flow_session_id, created_at, last_activity_at,
                        title, user_id, is_active, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        composite,
                        session.key.platform,
                        session.key.chat_type,
                        session.key.chat_id,
                        session.key.thread_id,
                        session.flow_session_id,
                        session.created_at.isoformat(),
                        session.last_activity_at.isoformat(),
                        session.title,
                        session.user_id,
                        1 if session.is_active else 0,
                        json.dumps(session.metadata, default=str),
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_write)

    async def list(
        self,
        platform: str | None = None,
        user_id: str | None = None,
        active_only: bool = True,
    ) -> list[GatewaySession]:
        """List sessions with optional filtering."""

        def _query() -> list[sqlite3.Row]:
            with self._get_connection() as conn:
                conditions: list[str] = []
                params: list[Any] = []

                if active_only:
                    conditions.append("is_active = 1")
                if platform:
                    conditions.append("platform = ?")
                    params.append(platform)
                if user_id:
                    conditions.append("user_id = ?")
                    params.append(user_id)

                where = ""
                if conditions:
                    where = "WHERE " + " AND ".join(conditions)

                rows = conn.execute(
                    f"SELECT * FROM gateway_sessions {where} ORDER BY last_activity_at DESC",
                    params,
                ).fetchall()
                return rows

        rows = await asyncio.to_thread(_query)
        return [self._row_to_session(row) for row in rows]

    async def close_session(self, key: GatewaySessionKey) -> None:
        """Mark a session as inactive."""
        composite = key.composite_key()

        def _close() -> None:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE gateway_sessions SET is_active = 0, last_activity_at = ? WHERE composite_key = ?",
                    (datetime.now(timezone.utc).isoformat(), composite),
                )
                conn.commit()

        await asyncio.to_thread(_close)

    async def delete(self, key: GatewaySessionKey) -> None:
        """Permanently remove a session."""
        composite = key.composite_key()

        def _delete() -> None:
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM gateway_sessions WHERE composite_key = ?",
                    (composite,),
                )
                conn.commit()

        await asyncio.to_thread(_delete)

    async def cleanup_expired(self, ttl_seconds: int) -> int:
        """Remove sessions that have exceeded the TTL."""

        def _cleanup() -> int:
            with self._get_connection() as conn:
                # Calculate cutoff timestamp
                from datetime import timedelta
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)).isoformat()
                result = conn.execute(
                    "DELETE FROM gateway_sessions WHERE last_activity_at < ?",
                    (cutoff,),
                )
                conn.commit()
                return result.rowcount

        count = await asyncio.to_thread(_cleanup)
        if count > 0:
            logger.info("Cleaned up %d expired gateway sessions", count)
        return count
