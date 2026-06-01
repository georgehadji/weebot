"""SQLite-backed state repository with connection pooling."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.connection_pool import (
    SQLiteConnectionPool,
    get_or_create_pool,
)

logger = logging.getLogger(__name__)


class SQLiteStateRepository(StateRepositoryPort):
    """Persist sessions to SQLite using connection pooling."""

    def __init__(self, db_path: str = "./weebot_sessions.db"):
        """
        Initialize repository with connection pool.
        
        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = Path(db_path)
        self._pool: Optional[SQLiteConnectionPool] = None
        self._initialized = False
    
    async def _get_pool(self) -> SQLiteConnectionPool:
        """Get or initialize the connection pool."""
        if self._pool is None:
            self._pool = await get_or_create_pool(
                self._db_path,
                max_read_connections=5,
                enable_wal=True
            )
            if not self._initialized:
                await self._ensure_schema()
                self._initialized = True
        return self._pool
    
    async def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        pool = await self._get_pool()
        
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT,
                    events_json TEXT NOT NULL DEFAULT '[]',
                    context_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            
            # Create index for user_id lookups
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_user_id 
                ON sessions(user_id)
                """
            )
            
            # Create index for status filtering
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_status 
                ON sessions(status)
                """
            )
            
            logger.debug("Database schema ensured")
    
    async def save_session(self, session: Session) -> None:
        """
        Save or update a session.
        
        Uses UPSERT (INSERT ... ON CONFLICT) for atomic updates.
        """
        pool = await self._get_pool()
        
        # Serialize session data
        events_data = [e.model_dump() for e in session.events]

        # Guard against event bloat: if JSON exceeds limit, keep only recent events
        from weebot.config.constants import MAX_EVENTS_JSON_BYTES
        events_json = json.dumps(events_data, default=str)
        while len(events_json) > MAX_EVENTS_JSON_BYTES and len(events_data) > 1:
            logger.warning(
                "Session %s events_json is %d bytes — truncating oldest events",
                session.id, len(events_json),
            )
            events_data = events_data[1:]
            events_json = json.dumps(events_data, default=str)

        async with pool.acquire_write() as conn:
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
                {
                    "id": session.id,
                    "user_id": session.user_id,
                    "agent_id": session.agent_id,
                    "status": session.status.value,
                    "title": session.title,
                    "events_json": events_json,
                    "context_json": json.dumps(session.context, default=str),
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                },
            )
            logger.debug(f"Session saved: {session.id}")
    
    async def load_session(self, session_id: str) -> Optional[Session]:
        """Load a session by ID."""
        pool = await self._get_pool()
        
        row = await pool.execute_read(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
            fetch_all=False
        )
        
        if not row:
            return None
        
        return self._row_to_session(row)
    
    async def list_sessions(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Session]:
        """
        List sessions with optional filtering.
        
        Args:
            user_id: Filter by user ID
            status: Filter by status string
            limit: Maximum number of results
            offset: Number of results to skip
        """
        pool = await self._get_pool()
        
        # Build query dynamically
        where_clauses = []
        params = []
        
        if user_id:
            where_clauses.append("user_id = ?")
            params.append(user_id)
        
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)
        
        query = f"""
            SELECT * FROM sessions 
            {where_sql}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        rows = await pool.execute_read(query, tuple(params))
        
        return [self._row_to_session(row) for row in rows]
    
    async def update_session_status(self, session_id: str, status: SessionStatus) -> bool:
        """
        Update session status efficiently.
        
        Returns:
            True if session was found and updated, False otherwise
        """
        pool = await self._get_pool()
        
        async with pool.acquire_write() as conn:
            cursor = await conn.execute(
                """
                UPDATE sessions 
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, datetime.now(timezone.utc).isoformat(), session_id)
            )
            await cursor.close()
            
            # Check if any row was updated
            # Note: aiosqlite doesn't expose rowcount easily, so we check via SELECT
            # This is a bit inefficient but keeps the API clean
        
        # Verify the update by loading the session
        session = await self.load_session(session_id)
        if session and session.status == status:
            logger.debug(f"Session {session_id} status updated to {status.value}")
            return True
        return False
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Returns:
            True if session was found and deleted, False otherwise
        """
        pool = await self._get_pool()
        
        # Check if exists first
        existing = await self.load_session(session_id)
        if not existing:
            return False
        
        async with pool.acquire_write() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,)
            )
        
        logger.debug(f"Session deleted: {session_id}")
        return True
    
    async def count_sessions(self, user_id: Optional[str] = None) -> int:
        """Count total sessions (optionally filtered by user)."""
        pool = await self._get_pool()
        
        if user_id:
            row = await pool.execute_read(
                "SELECT COUNT(*) as count FROM sessions WHERE user_id = ?",
                (user_id,),
                fetch_all=False
            )
        else:
            row = await pool.execute_read(
                "SELECT COUNT(*) as count FROM sessions",
                fetch_all=False
            )
        
        return row["count"] if row else 0
    
    # Lazily-initialized TypeAdapter for AgentEvent union
    _event_adapter = None

    @classmethod
    def _get_event_adapter(cls):
        if cls._event_adapter is None:
            from pydantic import TypeAdapter
            from weebot.domain.models.event import AgentEvent
            cls._event_adapter = TypeAdapter(AgentEvent)
        return cls._event_adapter

    def _row_to_session(self, row) -> Session:
        """Convert a database row to Session domain model."""
        from weebot.domain.models.event import MessageEvent, AgentEvent
        
        # Parse events JSON
        events_raw = json.loads(row["events_json"] or "[]")
        events = []
        adapter = self._get_event_adapter()
        for e in events_raw:
            try:
                events.append(adapter.validate_python(e))
            except Exception:
                # Fallback for malformed events
                events.append(MessageEvent(message=f"[unparseable event: {type(e).__name__}]"))
        
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            status=SessionStatus(row["status"]),
            title=row["title"],
            events=events,
            context=json.loads(row["context_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    
    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False
    
    def get_pool_stats(self) -> dict:
        """Get connection pool statistics."""
        if self._pool:
            return self._pool.get_stats()
        return {"initialized": False}
