"""SQLite-based event store for session logging and audit trails.

This module provides persistent storage for agent events, enabling:
- Complete session reconstruction for debugging
- Cost tracking and analytics
- Performance monitoring
- Session export for sharing

Based on patterns from The Dev Squad and Hyperagent analyses.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from weebot.application.ports.event_store_port import EventStorePort


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
        """Convert to dictionary for serialization."""
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
        """Convert to dictionary for serialization."""
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
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "user_id": self.user_id,
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
        }


class EventStore(EventStorePort):
    """SQLite-based event store for audit logging.

    Implements EventStorePort using synchronous sqlite3, wrapped with
    asyncio.to_thread for async compatibility.

    Example:
        >>> store = EventStore()
        >>> store.start_session("session-1", "user-1")
        >>> store.log_event("session-1", "llm_call", {"model": "gpt-4"}, 0.02, "gpt-4", 150)
        >>> events = store.get_session_events("session-1")
        >>> summary = store.get_cost_summary("session-1")
    """

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
        """Async wrapper for sync log_event. (EventStorePort implementation)"""
        return await asyncio.to_thread(
            self._sync_log_event, session_id, event_type, data, cost, model, tokens_used,
        )

    async def get_session_events(
        self,
        session_id: str,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Async wrapper for sync get_session_events. (EventStorePort implementation)"""
        events = await asyncio.to_thread(
            self._sync_get_session_events, session_id, event_type,
        )
        return [e.to_dict() for e in events]

    async def get_cost_summary(self, session_id: str) -> dict[str, Any]:
        """Async wrapper for sync get_cost_summary. (EventStorePort implementation)"""
        summary = await asyncio.to_thread(self._sync_get_cost_summary, session_id)
        return summary.to_dict()

    async def query_recent_events(
        self,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query recent events across all sessions, optionally filtered by type."""
        events = await asyncio.to_thread(
            self.query_events, event_type=event_type, limit=limit,
        )
        return [e.to_dict() if hasattr(e, "to_dict") else vars(e) for e in events]

    # ── Synchronous implementation ───────────────────────────────────

    def __init__(self, db_path: str = "~/.weebot/events.db"):
        """Initialize the event store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.executescript(
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

    @contextmanager
    def _get_connection(self):
        """Get a database connection as a context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def start_session(self, session_id: str, user_id: Optional[str] = None) -> None:
        """Record a new session.

        Args:
            session_id: Unique session identifier
            user_id: Optional user identifier
        """
        with self._get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (id, started_at, status, user_id)
                   VALUES (?, datetime('now'), 'active', ?)""",
                (session_id, user_id),
            )

    def _sync_log_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
        cost: float = 0.0,
        model: str = "",
        tokens_used: int = 0,
    ) -> int:
        """Log an event.

        Args:
            session_id: Session this event belongs to
            event_type: Type of event (e.g., 'llm_call', 'tool_call')
            data: Event-specific data dictionary
            cost: Cost of this event in USD
            model: Model used (if applicable)
            tokens_used: Tokens consumed (if applicable)

        Returns:
            Event ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO events
                   (session_id, event_type, data_json, cost, model, tokens_used)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, event_type, json.dumps(data), cost, model, tokens_used),
            )

            # Update session totals
            conn.execute(
                """UPDATE sessions
                   SET total_cost = total_cost + ?,
                       total_tokens = total_tokens + ?
                   WHERE id = ?""",
                (cost, tokens_used, session_id),
            )

            return cursor.lastrowid

    def _sync_get_session_events(
        self, session_id: str, event_type: Optional[str] = None
    ) -> list[Event]:
        """Get all events for a session.

        Args:
            session_id: Session to query
            event_type: Optional filter by event type

        Returns:
            List of events
        """
        with self._get_connection() as conn:
            if event_type:
                rows = conn.execute(
                    """SELECT * FROM events
                       WHERE session_id = ? AND event_type = ?
                       ORDER BY timestamp""",
                    (session_id, event_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM events
                       WHERE session_id = ?
                       ORDER BY timestamp""",
                    (session_id,),
                ).fetchall()

            return [
                Event(
                    id=row["id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    session_id=row["session_id"],
                    event_type=row["event_type"],
                    data=json.loads(row["data_json"]),
                    cost=row["cost"],
                    model=row["model"] or "",
                    tokens_used=row["tokens_used"],
                )
                for row in rows
            ]

    def _sync_get_cost_summary(self, session_id: str) -> CostSummary:
        """Get cost summary for a session.

        Args:
            session_id: Session to summarize

        Returns:
            CostSummary with totals and breakdown
        """
        with self._get_connection() as conn:
            # Get per-model breakdown
            rows = conn.execute(
                """SELECT model,
                          SUM(cost) as total_cost,
                          SUM(tokens_used) as total_tokens,
                          COUNT(*) as call_count
                   FROM events
                   WHERE session_id = ? AND model IS NOT NULL AND model != ''
                   GROUP BY model""",
                (session_id,),
            ).fetchall()

            model_breakdown = {
                row["model"]: {
                    "cost": row["total_cost"],
                    "tokens": row["total_tokens"],
                    "calls": row["call_count"],
                }
                for row in rows
            }

            # Get totals
            total = conn.execute(
                """SELECT total_cost, total_tokens FROM sessions WHERE id = ?""",
                (session_id,),
            ).fetchone()

            return CostSummary(
                total_cost=total["total_cost"] if total else 0.0,
                total_tokens=total["total_tokens"] if total else 0,
                model_breakdown=model_breakdown,
            )

    def end_session(self, session_id: str, status: str = "completed") -> None:
        """Mark a session as ended.

        Args:
            session_id: Session to end
            status: Final status ('completed', 'failed', 'cancelled')
        """
        with self._get_connection() as conn:
            conn.execute(
                """UPDATE sessions
                   SET ended_at = datetime('now'), status = ?
                   WHERE id = ?""",
                (status, session_id),
            )

    def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Get information about a session.

        Args:
            session_id: Session to query

        Returns:
            SessionInfo or None if not found
        """
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM sessions WHERE id = ?""", (session_id,)
            ).fetchone()

            if not row:
                return None

            return SessionInfo(
                id=row["id"],
                started_at=datetime.fromisoformat(row["started_at"]),
                ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                status=row["status"],
                user_id=row["user_id"],
                total_cost=row["total_cost"],
                total_tokens=row["total_tokens"],
            )

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SessionInfo]:
        """List sessions with optional filtering.

        Args:
            user_id: Filter by user
            status: Filter by status ('active', 'completed', 'failed')
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of SessionInfo
        """
        with self._get_connection() as conn:
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

            rows = conn.execute(query, params).fetchall()

            return [
                SessionInfo(
                    id=row["id"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                    status=row["status"],
                    user_id=row["user_id"],
                    total_cost=row["total_cost"],
                    total_tokens=row["total_tokens"],
                )
                for row in rows
            ]

    def query_events(
        self,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query events with filters.

        Args:
            event_type: Filter by type
            session_id: Filter by session
            start_time: Filter events after this time
            end_time: Filter events before this time
            limit: Maximum results

        Returns:
            List of events
        """
        with self._get_connection() as conn:
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

            rows = conn.execute(query, params).fetchall()

            return [
                Event(
                    id=row["id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    session_id=row["session_id"],
                    event_type=row["event_type"],
                    data=json.loads(row["data_json"]),
                    cost=row["cost"],
                    model=row["model"] or "",
                    tokens_used=row["tokens_used"],
                )
                for row in rows
            ]

    def get_recent_failed_sessions(self, limit: int = 10) -> list[SessionInfo]:
        """Get recent failed sessions.

        Args:
            limit: Maximum results

        Returns:
            List of failed SessionInfo
        """
        return self.list_sessions(status="failed", limit=limit)

    def export_session(self, session_id: str, format: str = "json") -> str:
        """Export session data.

        Args:
            session_id: Session to export
            format: 'json' or 'markdown'

        Returns:
            Exported data as string
        """
        events = self._sync_get_session_events(session_id)
        summary = self._sync_get_cost_summary(session_id)
        session_info = self.get_session_info(session_id)

        if format == "json":
            return json.dumps(
                {
                    "session": session_info.to_dict() if session_info else None,
                    "cost_summary": summary.to_dict(),
                    "events": [e.to_dict() for e in events],
                },
                indent=2,
            )

        elif format == "markdown":
            lines = [
                f"# Session Log: {session_id}",
                "",
                "## Summary",
            ]

            if session_info:
                lines.extend([
                    f"- Started: {session_info.started_at}",
                    f"- Status: {session_info.status}",
                    f"- User: {session_info.user_id or 'anonymous'}",
                ])

            lines.extend([
                "",
                "## Cost Summary",
                f"- Total Cost: ${summary.total_cost:.4f}",
                f"- Total Tokens: {summary.total_tokens:,}",
                "",
                "### Model Usage",
            ])

            for model, stats in summary.model_breakdown.items():
                lines.append(
                    f"- {model}: ${stats['cost']:.4f} ({stats['tokens']} tokens, {int(stats['calls'])} calls)"
                )

            lines.extend(["", "## Events"])
            for e in events:
                lines.append(f"\n### {e.event_type} ({e.timestamp.strftime('%H:%M:%S')})")
                lines.append(f"Model: {e.model or 'N/A'} | Cost: ${e.cost:.4f}")
                lines.append(f"```json\n{json.dumps(e.data, indent=2)}\n```")

            return "\n".join(lines)

        else:
            raise ValueError(f"Unknown format: {format}")

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its events.

        Args:
            session_id: Session to delete

        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            # Delete events first (foreign key constraint)
            conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))

            # Delete session
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Delete sessions older than specified days.

        Args:
            days: Age threshold in days

        Returns:
            Number of sessions deleted
        """
        # Validate input to prevent negative days
        if not isinstance(days, int) or days < 0:
            raise ValueError(f"days must be a non-negative integer, got {days}")

        with self._get_connection() as conn:
            # Use parameterized query for days (SQLite datetime with variable)
            # Note: SQLite datetime function doesn't support ? parameters directly for the modifier,
            # so we construct the modifier string safely after validation
            modifier = f"-{days} days"
            rows = conn.execute(
                """SELECT id FROM sessions
                   WHERE started_at < datetime('now', ?)""",
                (modifier,)
            ).fetchall()

            count = 0
            for row in rows:
                if self.delete_session(row["id"]):
                    count += 1

            return count

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics.

        Returns:
            Dictionary with statistics
        """
        with self._get_connection() as conn:
            session_count = conn.execute(
                "SELECT COUNT(*) as count FROM sessions"
            ).fetchone()["count"]

            event_count = conn.execute(
                "SELECT COUNT(*) as count FROM events"
            ).fetchone()["count"]

            total_cost = conn.execute(
                "SELECT SUM(total_cost) as total FROM sessions"
            ).fetchone()["total"] or 0.0

            total_tokens = conn.execute(
                "SELECT SUM(total_tokens) as total FROM sessions"
            ).fetchone()["total"] or 0

            return {
                "sessions": session_count,
                "events": event_count,
                "total_cost": total_cost,
                "total_tokens": total_tokens,
                "db_path": str(self.db_path),
                "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            }
