"""W5.1 (F26, F27): role ports over the SQLite-only repository methods.

`StateRepositoryPort` declares 7 methods; about 29 more exist only on
`SQLiteStateRepository` and were called by duck typing, from `domain/services`
too, so on `InMemoryStateRepository` or the PostgreSQL repo they raised
`AttributeError` (hidden by `except` blocks). Each group is now a typed role
port; a caller resolves its role once (`as_role`) and skips the feature when the
repository does not have it.

Typing the commitment role surfaced two defects in `CommitmentEngine`: it passed
a `limit=` the repository does not take, and read rows as objects
(`cmt.id`, `c.status`) while the repository returned dicts. Every heartbeat and
every chat-time commitment summary failed inside an `except`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from weebot.application.ports import state_roles_port as roles
from weebot.domain import ports as domain_ports
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

ROLE_PORTS = [
    roles.BehavioralRuleStore,
    roles.CorrectionStore,
    roles.SessionConstraintStore,
    roles.OpportunityStore,
    roles.MemoryMetadataStore,
    roles.PlanTemplateWriter,
    domain_ports.PlanTemplateStore,
    domain_ports.CommitmentStore,
]


@pytest.mark.parametrize("port", ROLE_PORTS, ids=lambda p: p.__name__)
def test_the_sqlite_repository_implements_every_role(port, tmp_path):
    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    assert domain_ports.as_role(repo, port) is repo


@pytest.mark.parametrize("port", ROLE_PORTS, ids=lambda p: p.__name__)
def test_a_repository_without_the_role_resolves_to_none(port):
    assert domain_ports.as_role(InMemoryStateRepository(), port) is None


def test_the_never_called_opportunity_methods_are_gone():
    for name in ("list_opportunities", "mark_opportunity_presented", "accept_opportunity"):
        assert not hasattr(SQLiteStateRepository, name), name


@pytest.mark.asyncio
async def test_the_commitment_engine_works_on_the_real_repository(tmp_path):
    from weebot.domain.models.commitment import Commitment, CommitmentStatus
    from weebot.domain.services.commitment_engine import CommitmentEngine

    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    now = datetime.now(UTC)
    await repo.save_commitment(
        Commitment(
            id="c-late", promise_text="send the report", context="", source_session_id="s1",
            due_at=now - timedelta(hours=1),
        )
    )
    await repo.save_commitment(
        Commitment(
            id="c-soon", promise_text="call back", context="", source_session_id="s1",
            due_at=now + timedelta(days=1),
        )
    )
    engine = CommitmentEngine(state_repo=repo)

    stats = await engine.heartbeat()
    assert stats["checked"] == 2 and stats["marked_overdue"] == 1

    summary = await engine.get_pending_summary()
    assert "send the report" in summary and "overdue" in summary
    assert "call back" in summary

    rows = await repo.list_commitments(status="overdue")
    assert [c.id for c in rows] == ["c-late"] and rows[0].status is CommitmentStatus.OVERDUE


@pytest.mark.asyncio
async def test_callers_skip_a_role_the_repository_lacks():
    from weebot.application.services.correction_tracker import CorrectionTracker
    from weebot.application.services.user_model_consolidator import UserModelConsolidator
    from weebot.domain.services.commitment_engine import CommitmentEngine
    from weebot.domain.services.plan_template_cache import find_matching_templates

    repo = InMemoryStateRepository()
    assert await CommitmentEngine(state_repo=repo).get_pending_summary() == ""
    assert await find_matching_templates(repo, "anything") == []
    assert await CorrectionTracker(state_repo=repo).get_recurring_patterns() == []
    await UserModelConsolidator(state_repo=repo).consolidate()


@pytest.mark.asyncio
async def test_an_opportunity_is_saved_with_its_fields():
    """`save_opportunity(proposal)` passed the model where the repository takes
    its fields: TypeError on every call, swallowed and logged as a warning."""
    from weebot.application.services.opportunity_engine import OpportunityEngine
    from weebot.domain.models.opportunity import OpportunityProposal

    saved = []

    class _Store:
        async def save_opportunity(self, opp_id, prompt, source, evidence=None,
                                   confidence=0.0, estimated_effort="medium"):
            saved.append((opp_id, prompt, source, confidence))

    engine = OpportunityEngine(state_repo=_Store())
    await engine._persist(
        [OpportunityProposal(id="o1", prompt="tidy logs", source="kg", confidence=0.9)]
    )
    assert saved == [("o1", "tidy logs", "kg", 0.9)]


@pytest.mark.asyncio
async def test_every_repository_can_count_sessions():
    """`count_sessions` is a session query, so it is on StateRepositoryPort with
    a default; the sessions router called it on any repository."""
    from weebot.domain.models.session import Session

    repo = InMemoryStateRepository()
    for i in range(3):
        await repo.save_session(Session(id=f"s{i}", user_id="u"))
    assert await repo.count_sessions(user_id="u") == 3
