"""Append-only hash-chained audit log for security-relevant events.

Records tool calls, approvals, denials, file writes, secret accesses,
and MCP connections in an append-only log with hash-chain integrity.

Each entry contains:
- ``sequence`` auto-incrementing counter
- ``timestamp`` ISO-8601
- ``event_type`` (tool_call, approval, denial, file_write, secret_access, mcp_connect, mcp_disconnect)
- ``details`` JSON-serializable dict with event-specific fields
- ``previous_hash`` SHA-256 of the previous entry
- ``hash`` SHA-256 of (sequence + timestamp + event_type + details + previous_hash)

The hash chain ensures tamper detection: changing any entry invalidates all
subsequent hashes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLog:
    """Append-only audit log with hash chain integrity.

    Each entry is linked to the previous one via SHA-256, making
    undetected tampering computationally infeasible for an attacker
    who cannot rewrite the entire chain.

    Usage:
        log = AuditLog()
        await log.record("tool_call", {"tool": "bash", "command": "ls"})
        entries = await log.query(event_type="tool_call")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else Path.home() / ".weebot" / "audit_log.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        """Initialize the audit log schema."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    previous_hash TEXT NOT NULL DEFAULT '',
                    hash TEXT NOT NULL
                )
            """)
            # Index for efficient queries by type and time
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_event_type
                ON audit_log(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_log(timestamp)
            """)
            conn.commit()

    def _compute_hash(
        self,
        sequence: int,
        timestamp: str,
        event_type: str,
        details: str,
        previous_hash: str,
    ) -> str:
        """Compute the SHA-256 hash for an audit entry."""
        payload = f"{sequence}|{timestamp}|{event_type}|{details}|{previous_hash}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_last_hash(self) -> str:
        """Get the hash of the most recent entry, or '' for the first entry."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT hash FROM audit_log ORDER BY sequence DESC LIMIT 1",
            ).fetchone()
            return row["hash"] if row else ""

    async def record(
        self,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Record a new audit log entry.

        Args:
            event_type: Type of event (tool_call, approval, denial, etc.).
            details: Event-specific data (tool name, command, user, etc.).

        Returns:
            Sequence number of the new entry.
        """
        details_json = json.dumps(details or {}, default=str)
        timestamp = datetime.now(timezone.utc).isoformat()
        previous_hash = self._get_last_hash()

        def _insert() -> int:
            with self._get_conn() as conn:
                # Get next sequence
                row = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM audit_log").fetchone()
                sequence = row["next_seq"]

                entry_hash = self._compute_hash(
                    sequence, timestamp, event_type, details_json, previous_hash,
                )

                conn.execute(
                    """INSERT INTO audit_log (sequence, timestamp, event_type, details, previous_hash, hash)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (sequence, timestamp, event_type, details_json, previous_hash, entry_hash),
                )
                conn.commit()
                return sequence

        return _insert()

    async def query(
        self,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query audit log entries.

        Args:
            event_type: Filter by event type (None = all types).
            limit: Max entries to return.
            offset: Skip N entries (for pagination).

        Returns:
            List of dicts with sequence, timestamp, event_type, details, hash.
        """
        def _query() -> list[dict[str, Any]]:
            with self._get_conn() as conn:
                if event_type:
                    rows = conn.execute(
                        """SELECT sequence, timestamp, event_type, details, previous_hash, hash
                           FROM audit_log WHERE event_type = ?
                           ORDER BY sequence DESC LIMIT ? OFFSET ?""",
                        (event_type, limit, offset),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """SELECT sequence, timestamp, event_type, details, previous_hash, hash
                           FROM audit_log ORDER BY sequence DESC LIMIT ? OFFSET ?""",
                        (limit, offset),
                    ).fetchall()

                results = []
                for row in rows:
                    results.append({
                        "sequence": row["sequence"],
                        "timestamp": row["timestamp"],
                        "event_type": row["event_type"],
                        "details": json.loads(row["details"]) if row["details"] else {},
                        "previous_hash": row["previous_hash"],
                        "hash": row["hash"],
                    })
                return results

        return _query()

    async def verify_integrity(self) -> list[int]:
        """Verify the hash chain integrity.

        Returns:
            List of sequence numbers of corrupted entries (empty if intact).
        """
        def _verify() -> list[int]:
            corrupted: list[int] = []
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT sequence, timestamp, event_type, details, previous_hash, hash
                       FROM audit_log ORDER BY sequence ASC""",
                ).fetchall()

                expected_previous = ""
                for row in rows:
                    expected_hash = self._compute_hash(
                        row["sequence"],
                        row["timestamp"],
                        row["event_type"],
                        row["details"],
                        expected_previous,
                    )
                    if expected_hash != row["hash"]:
                        corrupted.append(row["sequence"])
                    expected_previous = row["hash"]

            return corrupted

        return _verify()

    async def count(self, event_type: str | None = None) -> int:
        """Count entries, optionally filtered by type."""
        def _count() -> int:
            with self._get_conn() as conn:
                if event_type:
                    row = conn.execute(
                        "SELECT COUNT(*) AS cnt FROM audit_log WHERE event_type = ?",
                        (event_type,),
                    ).fetchone()
                else:
                    row = conn.execute("SELECT COUNT(*) AS cnt FROM audit_log").fetchone()
                return row["cnt"]

        return _count()
