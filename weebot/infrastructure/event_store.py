"""Async SQLite-based event store for session logging and audit trails.

Uses the shared aiosqlite connection pool (SQLiteConnectionPool) instead of
synchronous sqlite3 + asyncio.to_thread, eliminating thread pool contention.

Provides persistent storage for agent events, enabling:
- Complete session reconstruction for debugging
- Cost tracking and analytics
- Performance monitoring
- Session export for sharing
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.event_store_port import EventStorePort

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """A logged event in the system."""

    id: Optional[int]
    timestamp: datetime
    session_id: str
    event_type: str
    data: dict[str, Any]
    cost: float
    model: str
    tokens_used: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "event_type": self.event_type,
            "data": self.data,
            "cost": self.cost,
            "model": self.model,
            "tokens_used": self.tokens_used,
        }


@dataclass
class CostSummary:
    """Summary of costs for a session."""
    total_cost: float
    total_tokens: int
    model_breakdown: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
            "model_breakdown": self.model_breakdown,
        }


@dataclass
class SessionInfo:
    """Information about a session."""
    id: str
    started_at: datetime
    ended_at: Optional[datetime]
    status: str
    user_id: Optional[str]
    total_cost: float
    total_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "user_id": self.user_id,
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
        }


class AsyncEventStore(EventStorePort):
    """Async SQLite-based event store for audit logging.

    Uses the existing SQLiteConnectionPool (aiosqlite) for all operations,
    eliminating thread pool contention from the previous asyncio.to_thread approach.

    Example:
        store = AsyncEventStore()
        await store.log_event("session-1", "llm_call", {...}, 0.02, "gpt-4", 150)
        events = await store.get_session_events("session-1")
        summary = await store.get_cost_summary("session-1")
    """

    def __init__(self, db_path: str = "~/.weebot/events.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._pool: Optional["SQLiteConnectionPool"] = None  # noqa: F821

    async def _get_pool(self):
        """Lazy-init connection pool."""
        if self._pool is None:
            from weebot.infrastructure.persistence.connection_pool import get_or_create_pool
            self._pool = await get_or_create_pool(
                self.db_path, max_read_connections=3, enable_wal=True,
            )
            await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    user_id TEXT,
                    total_cost REAL DEFAULT 0.0,
                    total_tokens INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    cost REAL DEFAULT 0.0,
                    model TEXT,
                    tokens_used INTEGER DEFAULT 0,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_type
                    ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                    ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_sessions_status
                    ON sessions(status);
                CREATE INDEX IF NOT EXISTS idx_sessions_user
                    ON sessions(user_id);
                """
            )

    # ── EventStorePort async implementation ─────────────────────────

    async def log_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
        cost: float = 0.0,
        model: str = "",
        tokens_used: int = 0,
    ) -> int:
        """Log an event to the store.

        Returns the auto-generated event ID.
        """
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            cursor = await conn.execute(
                """INSERT INTO events
                   (session_id, event_type, data_json, cost, model, tokens_used)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, event_type, json.dumps(data), cost, model, tokens_used),
            )
            await conn.execute(
                """UPDATE sessions
                   SET total_cost = total_cost + ?,
                       total_tokens = total_tokens + ?
                   WHERE id = ?""",
                (cost, tokens_used, session_id),
            )
            return cursor.lastrowid

    async def get_session_events(
        self,
        session_id: str,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all events for a session, optionally filtered by type."""
        pool = await self._get_pool()
        if event_type:
            rows = await pool.execute_read(
                """SELECT * FROM events
                   WHERE session_id = ? AND event_type = ?
                   ORDER BY timestamp""",
                (session_id, event_type),
            )
        else:
            rows = await pool.execute_read(
                """SELECT * FROM events
                   WHERE session_id = ?
                   ORDER BY timestamp""",
                (session_id,),
            )
        return [self._row_to_event(r).to_dict() for r in rows]

    async def get_cost_summary(self, session_id: str) -> dict[str, Any]:
        """Get cost summary for a session."""
        pool = await self._get_pool()

        rows = await pool.execute_read(
            """SELECT model,
                      SUM(cost) as total_cost,
                      SUM(tokens_used) as total_tokens,
                      COUNT(*) as call_count
               FROM events
               WHERE session_id = ? AND model IS NOT NULL AND model != ''
               GROUP BY model""",
            (session_id,),
        )
        model_breakdown = {
            row["model"]: {
                "cost": row["total_cost"],
                "tokens": row["total_tokens"],
                "calls": row["call_count"],
            }
            for row in rows
        }

        total = await pool.execute_read(
            """SELECT total_cost, total_tokens FROM sessions WHERE id = ?""",
            (session_id,),
            fetch_all=False,
        )

        return CostSummary(
            total_cost=total["total_cost"] if total else 0.0,
            total_tokens=total["total_tokens"] if total else 0,
            model_breakdown=model_breakdown,
        ).to_dict()

    async def query_recent_events(
        self,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query recent events across all sessions."""
        events = await self.query_events(event_type=event_type, limit=limit)
        return [e.to_dict() for e in events]

    # ── Additional public methods ───────────────────────────────────

    async def start_session(self, session_id: str, user_id: Optional[str] = None) -> None:
        """Record a new session."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (id, started_at, status, user_id)
                   VALUES (?, datetime('now'), 'active', ?)""",
                (session_id, user_id),
            )

    async def end_session(self, session_id: str, status: str = "completed") -> None:
        """Mark a session as ended."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """UPDATE sessions
                   SET ended_at = datetime('now'), status = ?
                   WHERE id = ?""",
                (status, session_id),
            )

    async def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Get information about a session."""
        pool = await self._get_pool()
        row = await pool.execute_read(
            "SELECT * FROM sessions WHERE id = ?", (session_id,), fetch_all=False,
        )
        if not row:
            return None
        return self._row_to_session_info(row)

    async def list_sessions(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SessionInfo]:
        """List sessions with optional filtering."""
        pool = await self._get_pool()
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[Any] = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = await pool.execute_read(query, tuple(params))
        return [self._row_to_session_info(r) for r in rows]

    async def query_events(
        self,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query events with filters."""
        pool = await self._get_pool()
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = await pool.execute_read(query, tuple(params))
        return [self._row_to_event(r) for r in rows]

    async def get_recent_failed_sessions(self, limit: int = 10) -> list[SessionInfo]:
        """Get recent failed sessions."""
        return await self.list_sessions(status="failed", limit=limit)

    async def export_session(self, session_id: str, format: str = "json") -> str:
        """Export session data as JSON or Markdown."""
        events = await self._get_session_events_raw(session_id)
        summary = await self.get_cost_summary(session_id)
        session_info = await self.get_session_info(session_id)
        summary_obj = CostSummary(**summary) if isinstance(summary, dict) else summary

        if format == "json":
            return json.dumps({
                "session": session_info.to_dict() if session_info else None,
                "cost_summary": summary_obj.to_dict() if hasattr(summary_obj, "to_dict") else summary,
                "events": [e.to_dict() for e in events],
            }, indent=2)

        elif format == "markdown":
            lines = [f"# Session Log: {session_id}", "", "## Summary"]
            if session_info:
                lines.append(f"- Started: {session_info.started_at}")
                lines.append(f"- Status: {session_info.status}")
                lines.append(f"- User: {session_info.user_id or 'anonymous'}")
            lines.extend(["", "## Cost Summary"])
            lines.append(f"- Total Cost: ${summary_obj.total_cost:.4f}")
            lines.append(f"- Total Tokens: {summary_obj.total_tokens:,}")
            lines.extend(["", "### Model Usage"])
            for model, stats in summary_obj.model_breakdown.items():
                lines.append(
                    f"- {model}: ${stats['cost']:.4f} ({stats['tokens']} tokens, {int(stats['calls'])} calls)"
                )
            lines.extend(["", "## Events"])
            for e in events:
                lines.append(f"\n### {e.event_type} ({e.timestamp.strftime('%H:%M:%S')})")
                lines.append(f"Model: {e.model or 'N/A'} | Cost: ${e.cost:.4f}")
                lines.append(f"```json\n{json.dumps(e.data, indent=2)}\n```")
            return "\n".join(lines)

        raise ValueError(f"Unknown format: {format}")

    async def _get_session_events_raw(self, session_id: str) -> list[Event]:
        """Get raw Event objects (internal helper for export)."""
        pool = await self._get_pool()
        rows = await pool.execute_read(
            "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        return [self._row_to_event(r) for r in rows]

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its events."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0

    async def cleanup_old_sessions(self, days: int = 30) -> int:
        """Delete sessions older than specified days."""
        if not isinstance(days, int) or days < 0:
            raise ValueError(f"days must be a non-negative integer, got {days}")

        pool = await self._get_pool()
        modifier = f"-{days} days"
        rows = await pool.execute_read(
            "SELECT id FROM sessions WHERE started_at < datetime('now', ?)",
            (modifier,),
        )
        count = 0
        for row in rows:
            if await self.delete_session(row["id"]):
                count += 1
        return count

    async def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        pool = await self._get_pool()

        session_count_row = await pool.execute_read(
            "SELECT COUNT(*) as count FROM sessions", fetch_all=False,
        )
        event_count_row = await pool.execute_read(
            "SELECT COUNT(*) as count FROM events", fetch_all=False,
        )
        total_row = await pool.execute_read(
            "SELECT SUM(total_cost) as total, SUM(total_tokens) as tokens FROM sessions",
            fetch_all=False,
        )

        return {
            "sessions": session_count_row["count"] if session_count_row else 0,
            "events": event_count_row["count"] if event_count_row else 0,
            "total_cost": total_row["total"] if total_row and total_row["total"] else 0.0,
            "total_tokens": total_row["tokens"] if total_row and total_row["tokens"] else 0,
            "db_path": str(self.db_path),
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
        }

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── Row mapping helpers ────────────────────────────────────────

    @staticmethod
    def _row_to_event(row) -> Event:
        """Convert a DB row to Event domain object."""
        return Event(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            session_id=row["session_id"],
            event_type=row["event_type"],
            data=json.loads(row["data_json"]),
            cost=row["cost"],
            model=row["model"] or "",
            tokens_used=row["tokens_used"],
        )

    @staticmethod
    def _row_to_session_info(row) -> SessionInfo:
        """Convert a DB row to SessionInfo."""
        return SessionInfo(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            status=row["status"],
            user_id=row["user_id"],
            total_cost=row["total_cost"],
            total_tokens=row["total_tokens"],
        )


# Backward-compatible alias — existing importers use `EventStore`
EventStore = AsyncEventStore
