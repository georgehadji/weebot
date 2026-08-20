"""Real-SQLite regression tests for the memory_metadata salience pipeline (Phase 1 / F1).

Every existing test in this area used AsyncMock or InMemoryStateRepository
(which returns [] unconditionally), so none of them could catch the arity
mismatch, the write-once ON CONFLICT clause, or the ASC+LIMIT profile-lookup
bug. These tests exercise a real SQLiteStateRepository against a tmp_path DB.
"""

from __future__ import annotations

import pytest

from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository
from weebot.infrastructure.persistence.postgresql.state_repo import PostgreSQLStateRepository


def _repo(tmp_path) -> SQLiteStateRepository:
    return SQLiteStateRepository(db_path=str(tmp_path / "test_salience.db"))


class TestUpsertMemoryMetadataSalience:
    async def test_salience_kwarg_accepted_and_stored(self, tmp_path):
        """Fails before the fix with:
        TypeError: upsert_memory_metadata() got an unexpected keyword argument 'salience'
        """
        repo = _repo(tmp_path)
        await repo.upsert_memory_metadata("h1", "text one", "user", salience=1.0)
        row = await repo.get_memory_entry("h1")
        assert row is not None
        assert row["salience"] == 1.0

    async def test_default_insert_salience_is_half(self, tmp_path):
        repo = _repo(tmp_path)
        await repo.upsert_memory_metadata("h1", "text one", "agent")
        row = await repo.get_memory_entry("h1")
        assert row["salience"] == 0.5

    async def test_conflict_updates_entry_text_and_source(self, tmp_path):
        """The ON CONFLICT branch must update entry_text/source, or the pinned
        user profile is write-once and can never change agent->user."""
        repo = _repo(tmp_path)
        await repo.upsert_memory_metadata("h1", "first draft", "agent")
        await repo.upsert_memory_metadata("h1", "second draft", "user", salience=1.0)
        row = await repo.get_memory_entry("h1")
        assert row["entry_text"] == "second draft"
        assert row["source"] == "user"
        assert row["salience"] == 1.0

    async def test_explicit_salience_never_lowers_existing_score(self, tmp_path):
        """A pinned high-value entry must not decay on a later, lower-salience write."""
        repo = _repo(tmp_path)
        await repo.upsert_memory_metadata("h1", "v1", "user", salience=1.0)
        await repo.upsert_memory_metadata("h1", "v2", "user", salience=0.2)
        row = await repo.get_memory_entry("h1")
        assert row["salience"] == 1.0

    async def test_access_count_bump_path_without_salience_arg(self, tmp_path):
        """Repeated upserts with no explicit salience follow the +0.05 accumulate model."""
        repo = _repo(tmp_path)
        await repo.upsert_memory_metadata("h1", "text", "agent")
        await repo.upsert_memory_metadata("h1", "text", "agent")
        row = await repo.get_memory_entry("h1")
        assert row["access_count"] == 2
        assert row["salience"] == pytest.approx(0.55)


class TestGetMemoryEntry:
    async def test_missing_entry_returns_none(self, tmp_path):
        repo = _repo(tmp_path)
        assert await repo.get_memory_entry("does-not-exist") is None

    async def test_pinned_profile_found_past_five_lower_salience_rows(self, tmp_path):
        """The bug this replaces: get_low_salience_entries(threshold=1.01, limit=5)
        is ORDER BY salience ASC LIMIT 5, so a pinned salience=1.0 row sorts last
        and vanishes once five lower-salience rows exist."""
        repo = _repo(tmp_path)
        for i in range(10):
            await repo.upsert_memory_metadata(f"low{i}", f"noise {i}", "agent")
        await repo.upsert_memory_metadata("profile", "PROFILE-XYZ", "user", salience=1.0)
        row = await repo.get_memory_entry("profile")
        assert row is not None
        assert row["entry_text"] == "PROFILE-XYZ"


class TestUserProfileInjection:
    async def test_prompt_builder_finds_pinned_profile(self, tmp_path):
        from weebot.application.agents.executor._prompt_builder import build_executor_prompt

        repo = _repo(tmp_path)
        import hashlib

        key = hashlib.sha256(b"user_model_profile").hexdigest()[:16]
        for i in range(10):
            await repo.upsert_memory_metadata(f"low{i}", f"noise {i}", "agent")
        await repo.upsert_memory_metadata(key, "PROFILE-XYZ", "user", salience=1.0)

        prompt = await build_executor_prompt(
            step_description="do a thing", base_prompt="base", state_repo=repo
        )
        assert "PROFILE-XYZ" in prompt


class TestTrackSalienceWarnOnce:
    async def test_repo_failure_warns_once_not_per_entry(self, caplog, tmp_path):
        """persistent_memory.py:149-151 calls _track_salience once per entry on
        every read (32 entries on a real AGENT.md) — a bare except swallowed
        every failure silently; the fix must log at most once per tool instance."""
        import logging
        from unittest.mock import AsyncMock, MagicMock
        from weebot.tools.persistent_memory import PersistentMemoryTool
        from weebot.infrastructure.persistence.filesystem_memory import FileSystemMemoryAdapter

        broken_repo = MagicMock()
        broken_repo.upsert_memory_metadata = AsyncMock(side_effect=RuntimeError("boom"))
        tool = PersistentMemoryTool(
            memory=FileSystemMemoryAdapter(memory_dir=tmp_path), state_repo=broken_repo
        )

        with caplog.at_level(logging.WARNING, logger="weebot.tools.persistent_memory"):
            await tool._track_salience("entry one", "agent")
            await tool._track_salience("entry two", "agent")
            await tool._track_salience("entry three", "agent")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert broken_repo.upsert_memory_metadata.await_count == 3


class TestPortAdapterInstantiation:
    """upsert_memory_metadata/get_memory_entry/delete_memory_entries are duck-typed,
    not @abstractmethod on StateRepositoryPort. Instantiation alone is the assertion —
    test_port_contracts.py filters out abstract classes and would silently drop a
    broken adapter rather than fail."""

    def test_all_three_impls_instantiate(self, tmp_path):
        SQLiteStateRepository(db_path=str(tmp_path / "x.db"))
        InMemoryStateRepository()
        PostgreSQLStateRepository()
