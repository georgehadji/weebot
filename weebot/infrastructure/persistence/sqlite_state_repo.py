"""SQLite-backed state repository with connection pooling.

This is a facade that delegates domain-specific operations to
dedicated helper classes in the same package.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.correction import CorrectionRecord
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
from weebot.infrastructure.persistence._session_queries import SessionQueries
from weebot.infrastructure.persistence._memory_metadata_repo import MemoryMetadataRepo
from weebot.infrastructure.persistence._commitment_repo import CommitmentRepo
from weebot.application.ports.database_router_port import DatabaseRouterPort
from weebot.infrastructure.persistence.default_database_router import DefaultDatabaseRouter
from weebot.infrastructure.persistence._behavioral_rule_repo import (
    BehavioralRuleRepo,
    OpportunityRepo,
    PlanTemplateRepo,
)
from weebot.infrastructure.persistence._correction_repo import CorrectionRecordRepo
from weebot.infrastructure.persistence._session_constraint_repo import SessionConstraintRepo

logger = logging.getLogger(__name__)


class SQLiteStateRepository(StateRepositoryPort):
    """Persist sessions to SQLite using connection pooling.

    Domain-specific operations are delegated to sub-repositories:
    ``._session_queries``, ``._memory_metadata``, ``._commitments``,
    ``._behavioral_rules``, ``._opportunities``, ``._plan_templates``,
    ``._corrections``, ``._session_constraints``.
    """

    def __init__(
        self,
        db_path: str = "./weebot_sessions.db",
        database_router: DatabaseRouterPort | None = None,
    ):
        self._db_path = Path(db_path)
        self._database_router = database_router or DefaultDatabaseRouter(db_path=db_path)
        self._pool: SQLiteConnectionPool | None = None
        self._initialized = False
        # Per-instance FTS5 index tracker (session_id → event count indexed).
        self._fts5_indexed: dict[str, int] = {}
        # Per-session locks to prevent concurrent FTS5 indexing races.
        self._fts5_locks: dict[str, asyncio.Lock] = {}
        # Sub-repositories (lazily initialized)
        self._session_queries: SessionQueries | None = None
        self._memory_metadata: MemoryMetadataRepo | None = None
        self._commitments: CommitmentRepo | None = None
        self._behavioral_rules: BehavioralRuleRepo | None = None
        self._opportunities: OpportunityRepo | None = None
        self._plan_templates: PlanTemplateRepo | None = None
        self._corrections: CorrectionRecordRepo | None = None
        self._session_constraints: SessionConstraintRepo | None = None

    # ── Connection management ───────────────────────────────────────

    async def _get_pool(self) -> SQLiteConnectionPool:
        if self._pool is None:
            db_path = self._database_router.get_db_path("sessions")
            pool = await get_or_create_pool(Path(db_path), max_read_connections=5, enable_wal=True)
            await self._ensure_schema(pool)
            self._pool = pool
            self._initialized = True
        return self._pool

    async def _init_helpers(self) -> None:
        """Lazily initialise sub-repositories once the pool is available."""
        if self._session_queries is not None:
            return
        pool = await self._get_pool()
        self._session_queries = SessionQueries(pool)
        self._memory_metadata = MemoryMetadataRepo(pool)
        self._commitments = CommitmentRepo(pool)
        self._behavioral_rules = BehavioralRuleRepo(pool)
        self._opportunities = OpportunityRepo(pool)
        self._plan_templates = PlanTemplateRepo(pool)
        self._corrections = CorrectionRecordRepo(pool)
        self._session_constraints = SessionConstraintRepo(pool)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def get_pool_stats(self) -> dict:
        """Return connection pool statistics."""
        pool = await self._get_pool()
        return pool.get_stats()

    # ── Schema ──────────────────────────────────────────────────────

    async def _ensure_schema(self, pool: SQLiteConnectionPool) -> None:
        """Create tables if they don't exist."""
        async with pool.acquire_write() as conn:
            await conn.execute("""
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
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"
            )
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)")
            await conn.execute("""
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
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opp_presented ON pending_opportunities(presented)"
            )
            await ensure_fts5_table(conn)
            await conn.execute("""
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
                """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_metadata (
                    entry_hash TEXT PRIMARY KEY,
                    entry_text TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'agent',
                    salience REAL NOT NULL DEFAULT 0.5,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed TEXT,
                    created_at TEXT NOT NULL
                )
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_salience ON memory_metadata(salience)"
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS plan_templates (
                    template_id TEXT PRIMARY KEY,
                    task_hash TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    success_score REAL NOT NULL DEFAULT 1.0,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                )
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plan_templates_hash ON plan_templates(task_hash)"
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS commitments (
                    id TEXT PRIMARY KEY,
                    promise_text TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    source_session_id TEXT NOT NULL,
                    source_event_id TEXT,
                    due_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    failure_reason TEXT
                )
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_commitments_due_at ON commitments(due_at)"
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS correction_records (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    step_description TEXT NOT NULL DEFAULT '',
                    original_output TEXT NOT NULL DEFAULT '',
                    corrected_output TEXT NOT NULL DEFAULT '',
                    correction_category TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_correction_category ON correction_records(correction_category)"
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_constraints (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    evidence_span TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'action',
                    direction TEXT NOT NULL DEFAULT 'tighten',
                    turn_index INTEGER NOT NULL DEFAULT 0,
                    revoked_at TEXT,
                    superseded_by TEXT,
                    created_at TEXT NOT NULL
                )
                """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sc_session ON session_constraints(session_id)"
            )
            logger.debug("Database schema ensured")

    # ── Session CRUD ────────────────────────────────────────────────

    async def save_session(self, session: Session) -> None:
        await self._init_helpers()
        sq = self._session_queries
        assert sq is not None

        # ── Extract commitments from assistant messages ───────────
        try:
            from weebot.domain.services.commitment_extractor import extract_commitments
            from weebot.domain.models.event import MessageEvent

            for event in session.events:
                if isinstance(event, MessageEvent) and getattr(event, "role", "") == "assistant":
                    text = getattr(event, "message", "") or ""
                    if text:
                        commitments = extract_commitments(
                            text,
                            context="Session: " + (session.title or "")[:200],
                            source_session_id=session.id,
                            source_event_id=getattr(event, "event_id", None),
                        )
                        for cmt in commitments:
                            await self.save_commitment(cmt)
        except Exception as exc:
            logger.debug("Commitment extraction skipped (non-fatal): %s", exc)

        # ── Event bloat guard ─────────────────────────────────────
        events_data = [e.model_dump() for e in session.events]
        from weebot.config.constants import MAX_EVENTS_JSON_BYTES

        events_json = json.dumps(events_data, default=str)
        while len(events_json) > MAX_EVENTS_JSON_BYTES and len(events_data) > 1:
            logger.warning(
                "Session %s events_json is %d bytes — truncating oldest events",
                session.id,
                len(events_json),
            )
            events_data = events_data[1:]
            events_json = json.dumps(events_data, default=str)
            self._fts5_indexed.pop(session.id, None)

        # ── Persist session ───────────────────────────────────────
        await sq.save(session)

        # ── Index new events for FTS5 ─────────────────────────────
        pool = await self._get_pool()
        if session.id not in self._fts5_locks:
            self._fts5_locks[session.id] = asyncio.Lock()
        async with self._fts5_locks[session.id]:
            last_indexed = self._fts5_indexed.get(session.id, 0)
            if len(session.events) < last_indexed:
                # Event list shrank (compaction) — the old watermark no longer
                # lines up with these positions. Same reset as the bloat-guard
                # branch above: re-index from scratch rather than silently
                # adopting a lower watermark and leaving the new event content
                # permanently unindexed.
                last_indexed = 0
                self._fts5_indexed.pop(session.id, None)
            new_events = session.events[last_indexed:]
            # Count what actually made it in. The watermark used to advance to
            # len(session.events) whether or not index_event raised, so any event
            # that failed to index was never retried and stayed permanently absent
            # from search -- the failure was logged, and then stepped over.
            indexed_count = 0
            async with pool.acquire_write() as conn:
                for event in new_events:
                    event_type = getattr(event, "type", "unknown")
                    summary = (
                        getattr(event, "message", "") or getattr(event, "summary", "") or event_type
                    )
                    content = ""
                    if hasattr(event, "details") and event.details:
                        content = str(event.details)[:1000]
                    try:
                        await index_event(conn, session.id, str(event_type), str(summary), content)
                    except Exception:
                        logger.warning("Failed to index event for FTS5", exc_info=True)
                        break
                    indexed_count += 1
            # Stop at the first failure and advance exactly as far as we got: the
            # failed event is retried on the next save, and the ones already
            # indexed are not duplicated.
            self._fts5_indexed[session.id] = last_indexed + indexed_count

    async def load_session(self, session_id: str) -> Session | None:
        await self._init_helpers()
        row = await self._session_queries.load(session_id)  # type: ignore[union-attr]
        if not row:
            return None
        return self._row_to_session(row)

    async def list_sessions(
        self,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        load_events: bool = False,
    ) -> list[Session]:
        """List sessions, optionally filtered by user/status.

        ``load_events`` defaults to False: most callers (list views, health
        checks, staleness scans, job scans) only read id/status/user_id, and
        deserializing every session's full event JSON here is O(sessions ×
        events) wasted work. Callers that actually inspect ``.events`` on the
        returned sessions (e.g. text/similarity search over event content)
        must pass ``load_events=True`` explicitly.
        """
        await self._init_helpers()
        rows = await self._session_queries.list(  # type: ignore[union-attr]
            user_id=user_id, status=status, limit=limit, offset=offset
        )
        if load_events:
            return [self._row_to_session(r, load_events=True) for r in rows]
        return [self._row_to_session(r, load_events=False) for r in rows]

    async def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        await self._init_helpers()
        await self._session_queries.update_status(session_id, status)  # type: ignore[union-attr]

    async def delete_session(self, session_id: str) -> None:
        await self._init_helpers()
        await self._session_queries.delete(session_id)  # type: ignore[union-attr]
        # Clean up FTS5 entries
        try:
            pool = await self._get_pool()
            async with pool.acquire_write() as conn:
                await conn.execute("DELETE FROM event_fts WHERE session_id = ?", (session_id,))
        except Exception:
            logger.debug("FTS5 cleanup skipped for %s", session_id)

    async def count_sessions(self, user_id: str | None = None) -> int:
        await self._init_helpers()
        return await self._session_queries.count(user_id)  # type: ignore[union-attr]

    async def search_sessions(self, query: str, limit: int = 20) -> list[dict]:
        query = query[:500]
        pool = await self._get_pool()
        return await search_events(pool, query, limit=limit)

    # ── Row mapping / helpers ──────────────────────────────────────

    _event_adapter = None

    @classmethod
    def _get_event_adapter(cls):
        if cls._event_adapter is None:
            from pydantic import TypeAdapter
            from weebot.domain.models.event import AgentEvent

            cls._event_adapter = TypeAdapter(AgentEvent)
        return cls._event_adapter

    def _row_to_session(self, row, load_events: bool = True) -> Session:
        """Convert a dict row to a Session domain object.

        Raises TypeError if row is not a mapping (defensive contract enforcement).
        """
        if not isinstance(row, dict):
            raise TypeError(f"_row_to_session requires a dict, got {type(row).__name__}")
        from weebot.domain.models.event import MessageEvent

        # Normalize to a plain dict: rows arrive as sqlite3.Row, which supports
        # bracket access but not the dict-style .get(default) used below for
        # optional columns (title, context_json).
        row = dict(row)
        events = []
        if load_events:
            events_raw = json.loads(row["events_json"] or "[]")
            adapter = self._get_event_adapter()
            for e in events_raw:
                try:
                    events.append(adapter.validate_python(e))
                except Exception:
                    events.append(MessageEvent(**e))
        from weebot.domain.models.session import SessionContext

        try:
            context_raw = json.loads(row["context_json"] or "{}")
        except (KeyError, TypeError):
            context_raw = {}
        context = SessionContext(**context_raw)
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            status=SessionStatus(row["status"]),
            title=row["title"] if row["title"] is not None else "",
            events=events,
            context=context,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # ── Behavioral rules ──────────────────────────────────────────

    async def save_behavioral_rule(
        self,
        rule_id: str,
        rule_text: str,
        source_session_id: str = "",
        source_message: str = "",
        scope: str = "global",
    ) -> None:
        await self._init_helpers()
        await self._behavioral_rules.save(rule_id, rule_text, source_session_id, source_message, scope)  # type: ignore[union-attr]

    async def list_behavioral_rules(self) -> list[dict]:
        await self._init_helpers()
        return await self._behavioral_rules.list()  # type: ignore[union-attr]

    # ── Corrections (ICM edit-source tracking) ──────────────────────

    async def save_correction_record(self, record: CorrectionRecord) -> None:
        await self._init_helpers()
        await self._corrections.save(record)  # type: ignore[union-attr]

    async def count_corrections_by_category(self, category: str) -> int:
        await self._init_helpers()
        return await self._corrections.count_by_category(category)  # type: ignore[union-attr]

    async def get_correction_patterns(self, min_count: int = 3) -> list[dict]:
        await self._init_helpers()
        return await self._corrections.get_patterns(min_count)  # type: ignore[union-attr]

    # ── Session constraints (Lost-in-Compaction SCs) ─────────────────

    async def save_session_constraint(self, session_id: str, constraint) -> None:
        await self._init_helpers()
        await self._session_constraints.save(session_id, constraint)  # type: ignore[union-attr]

    async def revoke_session_constraint(self, session_id: str, text: str, revoked_at) -> None:
        await self._init_helpers()
        await self._session_constraints.revoke(session_id, text, revoked_at)  # type: ignore[union-attr]

    async def list_active_session_constraints(self, session_id: str) -> list[dict]:
        await self._init_helpers()
        return await self._session_constraints.list_active(session_id)  # type: ignore[union-attr]

    # ── Opportunities ─────────────────────────────────────────────

    async def save_opportunity(
        self,
        opp_id: str,
        prompt: str,
        source: str,
        evidence: list[str] | None = None,
        confidence: float = 0.0,
        estimated_effort: str = "medium",
    ) -> None:
        await self._init_helpers()
        await self._opportunities.save(  # type: ignore[union-attr]
            opp_id, prompt, source, evidence, confidence, estimated_effort
        )

    async def list_opportunities(self, limit: int = 50) -> list[dict]:
        await self._init_helpers()
        return await self._opportunities.list(limit)  # type: ignore[union-attr]

    async def mark_opportunity_presented(self, opp_id: str) -> None:
        await self._init_helpers()
        await self._opportunities.mark_presented(opp_id)  # type: ignore[union-attr]

    async def accept_opportunity(self, opp_id: str) -> None:
        await self._init_helpers()
        await self._opportunities.accept(opp_id)  # type: ignore[union-attr]

    # ── Memory metadata ──────────────────────────────────────────

    async def upsert_memory_metadata(
        self, entry_hash: str, entry_text: str, source: str = "agent", salience: float | None = None
    ) -> None:
        await self._init_helpers()
        await self._memory_metadata.upsert(entry_hash, entry_text, source, salience)  # type: ignore[union-attr]

    async def get_low_salience_entries(self, threshold: float = 0.3, limit: int = 50) -> list[dict]:
        await self._init_helpers()
        return await self._memory_metadata.get_low_salience(threshold, limit)  # type: ignore[union-attr]

    async def get_memory_entry(self, entry_hash: str) -> dict | None:
        await self._init_helpers()
        return await self._memory_metadata.get_by_hash(entry_hash)  # type: ignore[union-attr]

    async def delete_memory_entries(self, entry_hashes: list[str]) -> int:
        await self._init_helpers()
        return await self._memory_metadata.delete_entries(entry_hashes)  # type: ignore[union-attr]

    # ── Plan templates ───────────────────────────────────────────

    async def save_plan_template(
        self, template_id: str, task_hash: str, task_description: str, plan_json: str
    ) -> None:
        await self._init_helpers()
        await self._plan_templates.save(template_id, task_hash, task_description, plan_json)  # type: ignore[union-attr]

    async def find_plan_templates_by_hash(self, task_hash: str) -> dict | None:
        await self._init_helpers()
        return await self._plan_templates.find_by_hash(task_hash)  # type: ignore[union-attr]

    async def list_all_plan_templates(self) -> list[dict]:
        await self._init_helpers()
        return await self._plan_templates.list_all()  # type: ignore[union-attr]

    async def increment_template_use(self, template_id: str) -> None:
        await self._init_helpers()
        await self._plan_templates.increment_use(template_id)  # type: ignore[union-attr]

    # ── Commitments ──────────────────────────────────────────────

    async def save_commitment(self, commitment, commit=True) -> None:
        await self._init_helpers()
        await self._commitments.save(  # type: ignore[union-attr]
            commitment_id=getattr(commitment, "id", ""),
            promise_text=getattr(commitment, "promise_text", ""),
            context=getattr(commitment, "context", ""),
            source_session_id=getattr(commitment, "source_session_id", ""),
            source_event_id=getattr(commitment, "source_event_id", None),
            due_at=getattr(commitment, "due_at", None),
            status=getattr(commitment, "status", "pending"),
        )

    async def list_commitments(self, status: str | None = None) -> list[dict]:
        await self._init_helpers()
        return await self._commitments.list(status)  # type: ignore[union-attr]

    async def get_pending_commitments(self) -> list[dict]:
        await self._init_helpers()
        return await self._commitments.get_pending()  # type: ignore[union-attr]

    async def update_commitment_status(
        self, commitment_id: str, status: str, failure_reason: str | None = None
    ) -> None:
        await self._init_helpers()
        await self._commitments.update_status(commitment_id, status, failure_reason)  # type: ignore[union-attr]
