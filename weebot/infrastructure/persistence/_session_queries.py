"""Session CRUD queries — extracted from SQLiteStateRepository for modularity."""

from __future__ import annotations

import json
import logging
from typing import Any

from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool
from datetime import UTC

logger = logging.getLogger(__name__)


class SessionQueries:
    """Encapsulates all session table CRUD operations.

    Shares a connection pool with the parent repository.
    """

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(self, session: Session) -> int:
        """Upsert a session row. Returns how many oldest events were dropped.

        The ``MAX_EVENTS_JSON_BYTES`` ceiling is enforced HERE and only here.
        ``SQLiteStateRepository.save_session`` used to run a byte-for-byte
        identical loop of its own immediately before calling this one, and then
        throw the result away — it passes the ``Session``, not the trimmed list,
        so this loop always re-did the work from the original events. One rule,
        two implementations, and the copy that ran first was the one nothing
        read.

        Returning the count is what lets the caller act on the outcome instead
        of recomputing it.
        """
        events_json, dropped = self._events_json(session)
        params = self._row_params(session, events_json)
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO sessions
                    (id, user_id, agent_id, status, title, events_json, context_json, created_at, updated_at)
                VALUES
                    (:id, :user_id, :agent_id, :status, :title, :events_json, :context_json, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    title = excluded.title,
                    events_json = excluded.events_json,
                    context_json = excluded.context_json,
                    updated_at = excluded.updated_at
                """,
                params,
            )
        return dropped

    async def save_if_unchanged(self, session: Session, expected_updated_at: str) -> bool:
        """Overwrite the row only if its ``updated_at`` is still *expected_updated_at*.

        One UPDATE on the single write connection, so nothing can write between the check and
        the write. False when the row changed (or is gone) and nothing was written.
        """
        events_json, _ = self._events_json(session)
        params = self._row_params(session, events_json) | {"expected": expected_updated_at}
        async with self._pool.acquire_write() as conn:
            cursor = await conn.execute(
                """
                UPDATE sessions SET
                    status = :status,
                    title = :title,
                    events_json = :events_json,
                    context_json = :context_json,
                    updated_at = :updated_at
                WHERE id = :id AND updated_at = :expected
                """,
                params,
            )
            return cursor.rowcount == 1

    @staticmethod
    def _row_params(session: Session, events_json: str) -> dict[str, Any]:
        return {
            "id": session.id,
            "user_id": session.user_id,
            "agent_id": session.agent_id,
            "status": session.status.value,
            "title": session.title,
            "events_json": events_json,
            "context_json": json.dumps(session.context.model_dump(mode="json")),
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }

    @staticmethod
    def _events_json(session: Session) -> tuple[str, int]:
        """The session's events as JSON under the byte ceiling, and how many were dropped."""
        events_data = [e.model_dump() for e in session.events]
        from weebot.config.constants import MAX_EVENTS_JSON_BYTES

        events_json = json.dumps(events_data, default=str)
        original_count = len(events_data)
        original_bytes = len(events_json)
        if original_bytes > MAX_EVENTS_JSON_BYTES:
            # Drop oldest first, but never the last plan: without it the next
            # step and every resume fail with NO_PLAN_FOUND. Sizes are summed
            # per event (+2 for the ", " separator) instead of re-dumping the
            # list after each drop.
            keep = max((i for i, e in enumerate(events_data) if e.get("type") == "plan"),
                       default=len(events_data) - 1)
            sizes = [len(json.dumps(e, default=str)) + 2 for e in events_data]
            total, drop = sum(sizes), set()
            for i in range(len(events_data)):
                if total <= MAX_EVENTS_JSON_BYTES or len(events_data) - len(drop) <= 1:
                    break
                if i != keep:
                    drop.add(i)
                    total -= sizes[i]
            events_data = [e for i, e in enumerate(events_data) if i not in drop]
            events_json = json.dumps(events_data, default=str)
        dropped = original_count - len(events_data)
        if dropped:
            # One line for the whole truncation, not one per dropped event.
            # With the duplicate loop in place this logged 2N lines for N
            # dropped events, from two different module names, which read like
            # two separate faults.
            logger.warning(
                "Session %s events_json was %d bytes over the %d-byte ceiling — "
                "dropped the %d oldest of %d events to fit the row",
                session.id,
                original_bytes,
                MAX_EVENTS_JSON_BYTES,
                dropped,
                original_count,
            )

        return events_json, dropped

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Load a session row by ID.

        Returns a dict (converted from aiosqlite.Row for type safety)."""
        row = await self._pool.execute_read(
            "SELECT * FROM sessions WHERE id = ?", (session_id,), fetch_all=False
        )
        return dict(row) if row is not None else None

    async def list(
        self,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List session rows with optional filters."""
        conditions: list[str] = []
        params: list[str] = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._pool.execute_read(
            f"SELECT * FROM sessions{where_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, str(limit), str(offset)),
        )
        return [dict(r) for r in rows]

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update just the status of a session."""
        from datetime import datetime

        async with self._pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now(UTC).isoformat(), session_id),
            )

    async def delete(self, session_id: str) -> None:
        """Delete a session row."""
        async with self._pool.acquire_write() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    async def count(self, user_id: str | None = None, status: str | None = None) -> int:
        """Count session rows, optionally filtered by user and status."""
        conditions: list[str] = []
        params: list[str] = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        row = await self._pool.execute_read(
            f"SELECT COUNT(*) as count FROM sessions{where_clause}",  # noqa: S608 - fixed clauses
            tuple(params),
            fetch_all=False,
        )
        return row["count"] if row else 0

    async def activity(
        self, session_ids: list[str]
    ) -> tuple[dict[str, dict[tuple[str, str], int]], dict[str, list[dict[str, Any]]]]:
        """Event counts by ``(type, status)`` and the plan and step events, per session.

        Two grouped queries per 500 ids over ``events_json`` (R19); events are not loaded.
        """
        counts: dict[str, dict[tuple[str, str], int]] = {sid: {} for sid in session_ids}
        plans: dict[str, list[dict[str, Any]]] = {sid: [] for sid in session_ids}
        ids = list(counts)
        for start in range(0, len(ids), 500):
            chunk = tuple(ids[start : start + 500])
            marks = ",".join("?" * len(chunk))
            rows = await self._pool.execute_read(
                "SELECT s.id AS sid, json_extract(e.value, '$.type') AS t,"
                " COALESCE(json_extract(e.value, '$.status'), '') AS st, COUNT(*) AS n"
                f" FROM sessions s, json_each(s.events_json) e WHERE s.id IN ({marks})"  # noqa: S608
                " GROUP BY sid, t, st",
                chunk,
            )
            for r in rows:
                counts[r["sid"]][(r["t"] or "", str(r["st"]))] = r["n"]
            rows = await self._pool.execute_read(
                "SELECT s.id AS sid, e.value AS v"
                f" FROM sessions s, json_each(s.events_json) e WHERE s.id IN ({marks})"  # noqa: S608
                " AND json_extract(e.value, '$.type') IN ('plan', 'step') ORDER BY sid, e.key",
                chunk,
            )
            for r in rows:
                plans[r["sid"]].append(json.loads(r["v"]))
        return counts, plans
