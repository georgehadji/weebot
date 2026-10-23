"""Repository roles beyond StateRepositoryPort (W5.1, F26).

``StateRepositoryPort`` declares the session methods every repository has.
``SQLiteStateRepository`` also stores behavioral rules, corrections, session
constraints, opportunities, memory metadata and plan templates; those methods
used to be reached by duck typing, so another repository raised
``AttributeError`` wherever they were called. Each group is a role here. A
caller resolves its role once with ``as_role`` and treats ``None`` as "this
repository does not keep that", skipping the feature.

The roles domain services need (plan-template reads, commitments) live in
``weebot.domain.ports`` and are re-exported below.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from weebot.domain.ports import CommitmentStore, PlanTemplateStore, as_role

__all__ = [
    "BehavioralRuleStore",
    "CommitmentStore",
    "CorrectionStore",
    "MemoryMetadataStore",
    "OpportunityStore",
    "PlanTemplateStore",
    "PlanTemplateWriter",
    "SessionConstraintStore",
    "as_role",
]


@runtime_checkable
class BehavioralRuleStore(Protocol):
    async def save_behavioral_rule(
        self,
        rule_id: str,
        rule_text: str,
        source_session_id: str = "",
        source_message: str = "",
        scope: str = "global",
    ) -> None: ...
    async def list_behavioral_rules(self) -> list[dict]: ...


@runtime_checkable
class CorrectionStore(Protocol):
    async def save_correction_record(self, record: Any) -> None: ...
    async def count_corrections_by_category(self, category: str) -> int: ...
    async def get_correction_patterns(self, min_count: int = 3) -> list[dict]: ...


@runtime_checkable
class SessionConstraintStore(Protocol):
    async def save_session_constraint(self, session_id: str, constraint: Any) -> None: ...
    async def revoke_session_constraint(
        self, session_id: str, text: str, revoked_at: Any
    ) -> None: ...
    async def list_active_session_constraints(self, session_id: str) -> list[dict]: ...


@runtime_checkable
class OpportunityStore(Protocol):
    async def save_opportunity(
        self,
        opp_id: str,
        prompt: str,
        source: str,
        evidence: list[str] | None = None,
        confidence: float = 0.0,
        estimated_effort: str = "medium",
    ) -> None: ...


@runtime_checkable
class MemoryMetadataStore(Protocol):
    async def upsert_memory_metadata(
        self, entry_hash: str, entry_text: str, source: str = "agent", salience: float | None = None
    ) -> None: ...
    async def delete_memory_entries(self, entry_hashes: list[str]) -> int: ...
    async def get_memory_entry(self, entry_hash: str) -> dict | None: ...


@runtime_checkable
class PlanTemplateWriter(Protocol):
    async def save_plan_template(
        self,
        template_id: str,
        task_hash: str,
        task_description: str,
        plan_json: str,
        success_score: float = 1.0,
    ) -> None: ...
    async def increment_template_use(self, template_id: str) -> None: ...
