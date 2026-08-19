"""Real-SQLite regression tests for SessionConstraintRepo.

Phase 1 of tasks/specs/side_constraint_integrity_plan.md. Mirrors
test_memory_metadata_repo.py's pattern: exercise a real SQLiteStateRepository
against a tmp_path DB rather than a mock, so the DDL/forwarder wiring is
actually proven.
"""
from __future__ import annotations

from datetime import datetime, timezone

from weebot.domain.models.session_constraint import (
    ConstraintDirection,
    ConstraintKind,
    SessionConstraint,
)
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


def _repo(tmp_path) -> SQLiteStateRepository:
    return SQLiteStateRepository(db_path=str(tmp_path / "test_session_constraints.db"))


def _c(text: str, turn_index: int = 0, **kw) -> SessionConstraint:
    return SessionConstraint(text=text, evidence_span=text, turn_index=turn_index, **kw)


class TestSaveAndListActive:
    async def test_saved_constraint_is_listed_active(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint("sess-1", _c("don't delete files"))
        rows = await repo.list_active_session_constraints("sess-1")
        assert len(rows) == 1
        assert rows[0]["text"] == "don't delete files"
        assert rows[0]["kind"] == "action"
        assert rows[0]["direction"] == "tighten"

    async def test_scoped_by_session_id(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint("sess-1", _c("a"))
        await repo.save_session_constraint("sess-2", _c("b"))
        rows = await repo.list_active_session_constraints("sess-1")
        assert [r["text"] for r in rows] == ["a"]

    async def test_ordered_by_turn_index(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint("sess-1", _c("second", turn_index=2))
        await repo.save_session_constraint("sess-1", _c("first", turn_index=1))
        rows = await repo.list_active_session_constraints("sess-1")
        assert [r["text"] for r in rows] == ["first", "second"]

    async def test_kind_and_direction_round_trip(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint(
            "sess-1",
            _c("use metric", kind=ConstraintKind.PREFERENCE, direction=ConstraintDirection.LOOSEN),
        )
        rows = await repo.list_active_session_constraints("sess-1")
        assert rows[0]["kind"] == "preference"
        assert rows[0]["direction"] == "loosen"


class TestRevoke:
    async def test_revoked_constraint_drops_out_of_active_list(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint("sess-1", _c("gone"))
        await repo.revoke_session_constraint("sess-1", "gone", datetime.now(timezone.utc))
        rows = await repo.list_active_session_constraints("sess-1")
        assert rows == []

    async def test_revoke_only_affects_matching_text(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint("sess-1", _c("a"))
        await repo.save_session_constraint("sess-1", _c("b"))
        await repo.revoke_session_constraint("sess-1", "a", datetime.now(timezone.utc))
        rows = await repo.list_active_session_constraints("sess-1")
        assert [r["text"] for r in rows] == ["b"]

    async def test_revoke_scoped_by_session_id(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.save_session_constraint("sess-1", _c("shared-text"))
        await repo.save_session_constraint("sess-2", _c("shared-text"))
        await repo.revoke_session_constraint("sess-1", "shared-text", datetime.now(timezone.utc))
        assert await repo.list_active_session_constraints("sess-1") == []
        assert len(await repo.list_active_session_constraints("sess-2")) == 1


class TestSchemaWiredThroughInitHelpers:
    async def test_repo_usable_without_manual_schema_setup(self, tmp_path):
        """_ensure_schema must create session_constraints on first pool access —
        no separate migration step required."""
        repo = _repo(tmp_path)
        # No prior call to _get_pool()/_init_helpers(); save_session_constraint
        # must trigger both internally, same as every other forwarder.
        await repo.save_session_constraint("sess-1", _c("x"))
        assert len(await repo.list_active_session_constraints("sess-1")) == 1
