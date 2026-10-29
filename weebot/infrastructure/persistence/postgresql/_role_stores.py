"""The role stores SQLiteStateRepository plays (behavioral rules, corrections,
constraints, opportunities, memory metadata, plan and workflow templates,
commitments), for PostgreSQL.

Same tables, columns and returned dict keys as the SQLite sub-repositories in
``weebot/infrastructure/persistence/_*_repo.py``; times stay ISO text so callers
see the same values on either backend. Without these the learning loops found
none of their roles on a Postgres repository and stored nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

ROLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_opportunities (
    id TEXT PRIMARY KEY, prompt TEXT NOT NULL, source TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]', confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    estimated_effort TEXT NOT NULL DEFAULT 'medium', created_at TEXT NOT NULL,
    presented INTEGER NOT NULL DEFAULT 0, accepted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS behavioral_rules (
    id TEXT PRIMARY KEY, rule_text TEXT NOT NULL,
    source_session_id TEXT NOT NULL DEFAULT '', source_message TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'global', created_at TEXT NOT NULL,
    applied_count INTEGER NOT NULL DEFAULT 0, last_applied_at TEXT
);
CREATE TABLE IF NOT EXISTS memory_metadata (
    entry_hash TEXT PRIMARY KEY, entry_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'agent', salience DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0, last_accessed TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_salience ON memory_metadata(salience);
CREATE TABLE IF NOT EXISTS plan_templates (
    template_id TEXT PRIMARY KEY, task_hash TEXT NOT NULL, task_description TEXT NOT NULL,
    plan_json TEXT NOT NULL, success_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    use_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_templates_hash ON plan_templates(task_hash);
CREATE TABLE IF NOT EXISTS workflow_templates (
    task_summary TEXT PRIMARY KEY, template_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY, promise_text TEXT NOT NULL, context TEXT NOT NULL DEFAULT '',
    source_session_id TEXT NOT NULL, source_event_id TEXT, due_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, failure_reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_commitments_natural_key
    ON commitments(source_session_id, source_event_id, promise_text);
CREATE TABLE IF NOT EXISTS correction_records (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, step_id TEXT NOT NULL,
    step_description TEXT NOT NULL DEFAULT '', original_output TEXT NOT NULL DEFAULT '',
    corrected_output TEXT NOT NULL DEFAULT '', correction_category TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_correction_category ON correction_records(correction_category);
CREATE TABLE IF NOT EXISTS session_constraints (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
    evidence_span TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'action',
    direction TEXT NOT NULL DEFAULT 'tighten', turn_index INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT, superseded_by TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sc_session ON session_constraints(session_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


class PostgresRoleStores:
    """Mixin for PostgreSQLStateRepository, which provides ``_execute`` and ``_fetch``."""

    async def _execute(self, sql: str, *args: Any) -> str:
        raise NotImplementedError

    async def _fetch(self, sql: str, *args: Any) -> list[dict]:
        raise NotImplementedError

    # ── Behavioral rules ──────────────────────────────────────────

    async def save_behavioral_rule(
        self,
        rule_id: str,
        rule_text: str,
        source_session_id: str = "",
        source_message: str = "",
        scope: str = "global",
    ) -> None:
        await self._execute(
            """INSERT INTO behavioral_rules
                   (id, rule_text, source_session_id, source_message, scope, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (id) DO UPDATE SET
                   rule_text = EXCLUDED.rule_text, scope = EXCLUDED.scope""",
            rule_id, rule_text, source_session_id, source_message, scope, _now(),
        )

    async def list_behavioral_rules(self) -> list[dict]:
        return await self._fetch("SELECT * FROM behavioral_rules ORDER BY created_at DESC")

    # ── Corrections ───────────────────────────────────────────────

    async def save_correction_record(self, record: Any) -> None:
        await self._execute(
            """INSERT INTO correction_records
                   (id, session_id, step_id, step_description, original_output,
                    corrected_output, correction_category, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            f"{record.session_id}:{record.step_id}:{record.created_at.isoformat()}",
            record.session_id,
            record.step_id,
            record.step_description,
            record.original_output,
            record.corrected_output,
            record.correction_category,
            record.created_at.isoformat(),
        )

    async def count_corrections_by_category(self, category: str) -> int:
        rows = await self._fetch(
            "SELECT COUNT(*) AS n FROM correction_records WHERE correction_category = $1",
            category,
        )
        return int(rows[0]["n"]) if rows else 0

    async def get_correction_patterns(self, min_count: int = 3) -> list[dict]:
        return await self._fetch(
            """SELECT correction_category AS category, COUNT(*) AS count
               FROM correction_records GROUP BY correction_category
               HAVING COUNT(*) >= $1 ORDER BY count DESC""",
            min_count,
        )

    # ── Session constraints ───────────────────────────────────────

    async def save_session_constraint(self, session_id: str, constraint: Any) -> None:
        await self._execute(
            """INSERT INTO session_constraints
                   (id, session_id, text, evidence_span, kind, direction,
                    turn_index, revoked_at, superseded_by, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            f"{session_id}:{constraint.turn_index}:{constraint.created_at.isoformat()}",
            session_id,
            constraint.text,
            constraint.evidence_span,
            constraint.kind.value,
            constraint.direction.value,
            constraint.turn_index,
            _iso(constraint.revoked_at) if constraint.revoked_at else None,
            constraint.superseded_by,
            constraint.created_at.isoformat(),
        )

    async def revoke_session_constraint(self, session_id: str, text: str, revoked_at: Any) -> None:
        await self._execute(
            """UPDATE session_constraints SET revoked_at = $1
               WHERE session_id = $2 AND text = $3
                 AND revoked_at IS NULL AND superseded_by IS NULL""",
            _iso(revoked_at), session_id, text,
        )

    async def list_active_session_constraints(self, session_id: str) -> list[dict]:
        return await self._fetch(
            """SELECT text, evidence_span, kind, direction, turn_index, created_at
               FROM session_constraints
               WHERE session_id = $1 AND revoked_at IS NULL AND superseded_by IS NULL
               ORDER BY turn_index ASC""",
            session_id,
        )

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
        await self._execute(
            """INSERT INTO pending_opportunities
                   (id, prompt, source, evidence, confidence, estimated_effort, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (id) DO UPDATE SET
                   prompt = EXCLUDED.prompt, confidence = EXCLUDED.confidence""",
            opp_id, prompt, source, [str(e) for e in evidence or []], confidence,
            estimated_effort, _now(),
        )

    # ── Memory metadata ───────────────────────────────────────────

    async def upsert_memory_metadata(
        self, entry_hash: str, entry_text: str, source: str = "agent", salience: float | None = None
    ) -> None:
        # Without a salience, each access raises the score by 0.05 (capped at 1);
        # with one, the score can only go up to it, never down.
        await self._execute(
            """INSERT INTO memory_metadata
                   (entry_hash, entry_text, source, salience, access_count, last_accessed,
                    created_at)
               VALUES ($1, $2, $3, $4, 1, $6, $6)
               ON CONFLICT (entry_hash) DO UPDATE SET
                   entry_text = EXCLUDED.entry_text,
                   source = EXCLUDED.source,
                   access_count = memory_metadata.access_count + 1,
                   salience = CASE
                       WHEN $5::double precision IS NOT NULL
                           THEN GREATEST(memory_metadata.salience, $5::double precision)
                       ELSE LEAST(1.0, memory_metadata.salience + 0.05)
                   END,
                   last_accessed = $6""",
            entry_hash, entry_text, source, 0.5 if salience is None else salience, salience,
            _now(),
        )

    async def get_low_salience_entries(self, threshold: float = 0.3, limit: int = 50) -> list[dict]:
        return await self._fetch(
            """SELECT entry_hash, entry_text, source, salience, access_count,
                      last_accessed, created_at
               FROM memory_metadata WHERE salience < $1 ORDER BY salience ASC LIMIT $2""",
            threshold, limit,
        )

    async def get_memory_entry(self, entry_hash: str) -> dict | None:
        rows = await self._fetch(
            """SELECT entry_hash, entry_text, source, salience, access_count,
                      last_accessed, created_at
               FROM memory_metadata WHERE entry_hash = $1""",
            entry_hash,
        )
        return rows[0] if rows else None

    async def delete_memory_entries(self, entry_hashes: list[str]) -> int:
        if not entry_hashes:
            return 0
        status = await self._execute(
            "DELETE FROM memory_metadata WHERE entry_hash = ANY($1::text[])", list(entry_hashes)
        )
        return int(status.split()[-1]) if status else 0

    # ── Plan templates ────────────────────────────────────────────

    async def save_plan_template(
        self,
        template_id: str,
        task_hash: str,
        task_description: str,
        plan_json: str,
        success_score: float = 1.0,
    ) -> None:
        await self._execute(
            """INSERT INTO plan_templates
                   (template_id, task_hash, task_description, plan_json, success_score,
                    created_at, last_used_at)
               VALUES ($1, $2, $3, $4, $5, $6, $6)
               ON CONFLICT (template_id) DO UPDATE SET
                   plan_json = CASE WHEN EXCLUDED.success_score >= plan_templates.success_score
                                    THEN EXCLUDED.plan_json ELSE plan_templates.plan_json END,
                   task_description = EXCLUDED.task_description,
                   success_score = GREATEST(plan_templates.success_score, EXCLUDED.success_score),
                   last_used_at = $6""",
            template_id, task_hash, task_description, plan_json, success_score, _now(),
        )

    async def find_plan_templates_by_hash(self, task_hash: str, limit: int = 3) -> list[dict]:
        return await self._fetch(
            """SELECT * FROM plan_templates WHERE task_hash = $1
               ORDER BY success_score DESC, use_count DESC LIMIT $2""",
            task_hash, limit,
        )

    async def list_all_plan_templates(self, limit: int = 200) -> list[dict]:
        return await self._fetch(
            "SELECT * FROM plan_templates ORDER BY use_count DESC LIMIT $1", limit
        )

    async def increment_template_use(self, template_id: str) -> None:
        await self._execute(
            """UPDATE plan_templates SET use_count = use_count + 1, last_used_at = $1
               WHERE template_id = $2""",
            _now(), template_id,
        )

    # ── Workflow templates ────────────────────────────────────────

    async def save_workflow_template(self, task_summary: str, template_json: str) -> None:
        await self._execute(
            """INSERT INTO workflow_templates (task_summary, template_json, updated_at)
               VALUES ($1, $2, $3)
               ON CONFLICT (task_summary) DO UPDATE SET
                   template_json = EXCLUDED.template_json, updated_at = EXCLUDED.updated_at""",
            task_summary, template_json, _now(),
        )

    async def list_workflow_templates(self, limit: int = 200) -> list[str]:
        rows = await self._fetch(
            "SELECT template_json FROM workflow_templates ORDER BY updated_at DESC LIMIT $1", limit
        )
        return [r["template_json"] for r in rows]

    # ── Commitments ───────────────────────────────────────────────

    async def save_commitment(self, commitment: Any, commit: bool = True) -> None:
        await self._execute(
            """INSERT INTO commitments
                   (id, promise_text, context, source_session_id, source_event_id,
                    due_at, status, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
               ON CONFLICT DO NOTHING""",
            getattr(commitment, "id", ""),
            getattr(commitment, "promise_text", ""),
            getattr(commitment, "context", ""),
            getattr(commitment, "source_session_id", ""),
            getattr(commitment, "source_event_id", None) or "",
            _iso(getattr(commitment, "due_at", None)) or "",
            getattr(commitment, "status", "pending"),
            _now(),
        )

    async def list_commitments(self, status: str | None = None) -> list:
        from weebot.domain.models.commitment import Commitment

        if status:
            rows = await self._fetch(
                "SELECT * FROM commitments WHERE status = $1 ORDER BY created_at DESC", status
            )
        else:
            rows = await self._fetch("SELECT * FROM commitments ORDER BY created_at DESC")
        return [Commitment.from_row(r) for r in rows]

    async def update_commitment_status(
        self, commitment_id: str, status: str, failure_reason: str | None = None
    ) -> None:
        await self._execute(
            """UPDATE commitments SET status = $1, updated_at = $2, failure_reason = $3
               WHERE id = $4""",
            status, _now(), failure_reason or "", commitment_id,
        )
