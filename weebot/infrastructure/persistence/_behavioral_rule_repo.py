"""Behavioral rules, opportunities, and plan templates repos — extracted from SQLiteStateRepository."""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool

logger = logging.getLogger(__name__)


class BehavioralRuleRepo:
    """Manages the behavioral_rules table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(
        self,
        rule_id: str,
        rule_text: str,
        source_session_id: str = "",
        source_message: str = "",
        scope: str = "global",
    ) -> None:
        """Insert a behavioral rule."""
        now = datetime.now(UTC).isoformat()
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO behavioral_rules
                    (id, rule_text, source_session_id, source_message, scope, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    rule_text = excluded.rule_text,
                    scope = excluded.scope
                """,
                (rule_id, rule_text, source_session_id, source_message, scope, now),
            )

    async def list(self) -> list[dict]:
        """List all behavioral rules."""
        rows = await self._pool.execute_read(
            "SELECT * FROM behavioral_rules ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


class OpportunityRepo:
    """Manages the pending_opportunities table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(
        self,
        opp_id: str,
        prompt: str,
        source: str,
        evidence: list[str] | None = None,
        confidence: float = 0.0,
        estimated_effort: str = "medium",
    ) -> None:
        """Insert an opportunity."""
        now = datetime.now(UTC).isoformat()
        evidence_json = json.dumps(evidence or [], default=str)
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO pending_opportunities
                    (id, prompt, source, evidence, confidence, estimated_effort, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    prompt = excluded.prompt,
                    confidence = excluded.confidence
                """,
                (opp_id, prompt, source, evidence_json, confidence, estimated_effort, now),
            )

    async def list(self, limit: int = 50) -> list[dict]:
        """List opportunities, un-presented first."""
        rows = await self._pool.execute_read(
            """
            SELECT * FROM pending_opportunities
            ORDER BY presented ASC, confidence DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    async def mark_presented(self, opp_id: str) -> None:
        """Mark an opportunity as presented."""
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE pending_opportunities SET presented = 1 WHERE id = ?", (opp_id,)
            )

    async def accept(self, opp_id: str) -> None:
        """Mark an opportunity as accepted."""
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE pending_opportunities SET accepted = 1 WHERE id = ?", (opp_id,)
            )


class PlanTemplateRepo:
    """Manages the plan_templates table."""

    def __init__(self, pool: SQLiteConnectionPool):
        self._pool = pool

    async def save(
        self,
        template_id: str,
        task_hash: str,
        task_description: str,
        plan_json: str,
        success_score: float = 1.0,
    ) -> None:
        """Insert a plan template.

        `success_score` was absent from the parameter list and from the INSERT
        column list, while the column is declared `NOT NULL DEFAULT 1.0` — so
        every template would have persisted as a perfect one no matter what the
        caller computed. `CompletedState` computes it from the ratio of
        COMPLETED steps precisely so that a plan which mostly failed is not
        retrieved as a model to copy. (D77.)
        """
        now = datetime.now(UTC).isoformat()
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                """
                INSERT INTO plan_templates
                    (template_id, task_hash, task_description, plan_json,
                     success_score, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    use_count = use_count + 1,
                    last_used_at = ?
                """,
                (
                    template_id,
                    task_hash,
                    task_description,
                    plan_json,
                    success_score,
                    now,
                    now,
                    now,
                ),
            )

    async def find_by_hash(self, task_hash: str, limit: int = 3) -> list[dict]:
        """Find templates by exact task hash, best-used first.

        This returned a single row (`dict | None`) while its only caller
        assigned the result to a `list[PlanTemplate]` and returned it straight
        out of a function declared to return that type. It also took no `limit`,
        which is what the caller passed. (D76.)
        """
        rows = await self._pool.execute_read(
            "SELECT * FROM plan_templates WHERE task_hash = ? "
            "ORDER BY success_score DESC, use_count DESC LIMIT ?",
            (task_hash, limit),
        )
        return [dict(r) for r in rows or []]

    async def list_all(self, limit: int = 200) -> list[dict]:
        """List plan templates, best-used first."""
        rows = await self._pool.execute_read(
            "SELECT * FROM plan_templates ORDER BY use_count DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows or []]

    async def increment_use(self, template_id: str) -> None:
        """Increment use count for a template."""
        now = datetime.now(UTC).isoformat()
        async with self._pool.acquire_write() as conn:
            await conn.execute(
                "UPDATE plan_templates SET use_count = use_count + 1, last_used_at = ? WHERE template_id = ?",
                (now, template_id),
            )
