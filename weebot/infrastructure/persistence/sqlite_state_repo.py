"""SQLite-backed state repository with connection pooling."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.event import AgentEvent
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.connection_pool import (
    SQLiteConnectionPool,
    get_or_create_pool,
)
from weebot.infrastructure.persistence.fts5_search import (
    ensure_fts5_table,
    index_event,
    search_events,
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
        # Per-instance FTS5 index tracker (session_id → event count indexed).
        # Must be instance-level to avoid cross-instance pollution in tests.
        self._fts5_indexed: dict[str, int] = {}

    async def _get_pool(self) -> SQLiteConnectionPool:
        """Get or initialize the connection pool."""
        if self._pool is None:
            pool = await get_or_create_pool(
                self._db_path,
                max_read_connections=5,
                enable_wal=True,
            )
            await self._ensure_schema(pool)
            self._pool = pool  # only assign after schema is confirmed ready
            self._initialized = True
        return self._pool

    async def _ensure_schema(self, pool: SQLiteConnectionPool) -> None:
        """Create tables if they don't exist."""
        
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

            # ── Capability 7: pending_opportunities table ──
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_opportunities (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    source TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.0,
                    estimated_effort TEXT NOT NULL DEFAULT 'medium',
                    created_at TEXT NOT NULL,
                    presented INTEGER NOT NULL DEFAULT 0,
                    accepted INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_opp_presented
                ON pending_opportunities(presented)
                """
            )
            # ── FTS5 event search table ──────────────────
            await ensure_fts5_table(conn)

            # ── Behavioral rules ─────────────────────────
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS behavioral_rules (
                    id TEXT PRIMARY KEY,
                    rule_text TEXT NOT NULL,
                    source_session_id TEXT NOT NULL DEFAULT '',
                    source_message TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'global',
                    created_at TEXT NOT NULL,
                    applied_count INTEGER NOT NULL DEFAULT 0,
                    last_applied_at TEXT
                )
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
            # Reset FTS5 index tracker — truncated events need re-indexing
            self._fts5_indexed.pop(session.id, None)

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
                    "context_json": json.dumps(session.context.model_dump(mode="json")),
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                },
            )
            logger.debug(f"Session saved: {session.id}")
            
            # Index only NEW events for FTS5 search (avoid write amplification)
            last_indexed = self._fts5_indexed.get(session.id, 0)
            new_events = session.events[last_indexed:]
            for event in new_events:
                event_type = getattr(event, "type", "unknown")
                summary = getattr(event, "message", "") or getattr(event, "summary", "") or event_type
                content = ""
                if hasattr(event, "details") and event.details:
                    content = str(event.details)[:1000]
                try:
                    await index_event(
                        conn, session.id, str(event_type), str(summary), content,
                    )
                except Exception:
                    logger.warning("Failed to index event for FTS5", exc_info=True)
            self._fts5_indexed[session.id] = len(session.events)
    
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

        session = self._row_to_session(row)
        # Seed FTS5 index count to avoid re-indexing existing events
        self._fts5_indexed[session_id] = len(session.events)
        return session
    
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
        
        return [self._row_to_session(row, load_events=False) for row in rows]
    
    async def update_session_status(self, session_id: str, status: SessionStatus) -> bool:
        """
        Update session status efficiently.
        
        Returns:
            True if session was found and updated, False otherwise
        """
        pool = await self._get_pool()
        
        async with pool.acquire_write() as conn:
            cursor = await conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, datetime.now(timezone.utc).isoformat(), session_id),
            )
            updated = cursor.rowcount > 0
        if updated:
            logger.debug("Session %s status updated to %s", session_id, status.value)
        return updated
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Returns:
            True if session was found and deleted, False otherwise
        """
        pool = await self._get_pool()

        row = await pool.execute_read(
            "SELECT COUNT(*) as cnt FROM sessions WHERE id = ?",
            (session_id,),
            fetch_all=False,
        )
        if not row or row["cnt"] == 0:
            return False

        async with pool.acquire_write() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        logger.debug("Session deleted: %s", session_id)
        # Clear FTS5 index for this session
        try:
            from weebot.infrastructure.persistence.fts5_search import clear_session_events
            async with pool.acquire_write() as conn:
                await clear_session_events(conn, session_id)
        except Exception:
            pass
        self._fts5_indexed.pop(session_id, None)
        return True

    async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across all indexed sessions."""
        query = query[:500]  # prevent FTS5 tokeniser overload on unbounded input
        pool = await self._get_pool()
        return await search_events(pool, query, limit=limit)

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

    def _row_to_session(self, row, load_events: bool = True) -> Session:
        """Convert a database row to Session domain model.

        Args:
            row: Database row dict.
            load_events: When False, skip deserializing events (use for list views).
        """
        from weebot.domain.models.event import MessageEvent, AgentEvent
        
        events = []
        if load_events:
            # Parse events JSON
            events_raw = json.loads(row["events_json"] or "[]")
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
            context=json.loads(row["context_json"] or "{}") if row["context_json"] and row["context_json"] != "null" else {},
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    
    # ── Behavioral Rule persistence (Capability 5) ──────────────────

    async def save_behavioral_rule(self, rule: "BehavioralRule") -> None:
        """Persist a behavioral rule.

        Args:
            rule: The BehavioralRule to save.
        """
        from weebot.domain.models.behavioral_rule import BehavioralRule
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO behavioral_rules
                    (id, rule_text, source_session_id, source_message, scope,
                     created_at, applied_count, last_applied_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    rule.rule_text,
                    rule.source_session_id,
                    rule.source_message,
                    rule.scope,
                    rule.created_at.isoformat(),
                    rule.applied_count,
                    rule.last_applied_at.isoformat() if rule.last_applied_at else None,
                ),
            )

    async def list_behavioral_rules(self) -> list["BehavioralRule"]:
        """Load all persisted behavioral rules."""
        from weebot.domain.models.behavioral_rule import BehavioralRule
        pool = await self._get_pool()
        rows = await pool.execute_read(
            "SELECT * FROM behavioral_rules ORDER BY created_at DESC",
        )
        return [
            BehavioralRule(
                id=r["id"],
                rule_text=r["rule_text"],
                source_session_id=r["source_session_id"],
                source_message=r["source_message"],
                scope=r["scope"],
                created_at=datetime.fromisoformat(r["created_at"]),
                applied_count=r["applied_count"],
                last_applied_at=datetime.fromisoformat(r["last_applied_at"]) if r["last_applied_at"] else None,
            )
            for r in rows
        ]

    # ── Capability 7: Opportunity persistence ───────────────────────

    async def save_opportunity(self, proposal: "OpportunityProposal") -> None:
        """Save an opportunity proposal."""
        from weebot.domain.models.opportunity import OpportunityProposal
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO pending_opportunities
                    (id, prompt, source, evidence, confidence, estimated_effort,
                     created_at, presented, accepted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.id,
                    proposal.prompt,
                    proposal.source,
                    json.dumps(proposal.evidence),
                    proposal.confidence,
                    proposal.estimated_effort,
                    proposal.created_at.isoformat(),
                    1 if proposal.presented else 0,
                    1 if proposal.accepted else 0,
                ),
            )

    async def list_opportunities(
        self, only_unpresented: bool = False, limit: int = 10
    ) -> list["OpportunityProposal"]:
        """List opportunity proposals."""
        from weebot.domain.models.opportunity import OpportunityProposal
        pool = await self._get_pool()

        if only_unpresented:
            rows = await pool.execute_read(
                "SELECT * FROM pending_opportunities WHERE presented = 0 ORDER BY confidence DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = await pool.execute_read(
                "SELECT * FROM pending_opportunities ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        return [self._row_to_opportunity(r) for r in rows]

    async def mark_opportunity_presented(self, proposal_id: str) -> bool:
        """Mark an opportunity as presented."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE pending_opportunities SET presented = 1 WHERE id = ?",
                (proposal_id,),
            )
        return True

    async def accept_opportunity(self, proposal_id: str) -> bool:
        """Mark an opportunity as accepted by the user."""
        pool = await self._get_pool()
        async with pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE pending_opportunities SET accepted = 1, presented = 1 WHERE id = ?",
                (proposal_id,),
            )
        return True

    @staticmethod
    def _row_to_opportunity(row) -> "OpportunityProposal":
        """Convert a DB row to OpportunityProposal."""
        from weebot.domain.models.opportunity import OpportunityProposal
        return OpportunityProposal(
            id=row["id"],
            prompt=row["prompt"],
            source=row["source"],
            evidence=json.loads(row["evidence"] or "[]"),
            confidence=row["confidence"],
            estimated_effort=row["estimated_effort"],
            created_at=datetime.fromisoformat(row["created_at"]),
            presented=bool(row["presented"]),
            accepted=bool(row["accepted"]),
        )

    # ────────────────────────────────────────────────────────────────

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
