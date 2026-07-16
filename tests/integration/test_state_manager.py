"""Integration tests for SQLiteStateRepository (real SQLite, no mocks).

Replaces the original StateManager tests which were deleted with the
deprecated state_manager.py module.  Tests the StateRepositoryPort
contract via its live SQLite implementation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from weebot.application.ports.state_repo_port import StateRepositoryPort
from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository


@pytest.fixture
async def repo(tmp_db) -> StateRepositoryPort:
    """SQLiteStateRepository backed by a temp database."""
    r = SQLiteStateRepository(db_path=str(tmp_db))
    # Force pool initialization
    await r._get_pool()
    return r


@pytest.fixture
def sample_session() -> Session:
    """A sample session for testing."""
    return Session(
        id="test-session-001",
        user_id="test-user",
        status=SessionStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestSaveAndLoad:
    """Core save/load roundtrip testing."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, repo: StateRepositoryPort, sample_session: Session):
        await repo.save_session(sample_session)
        loaded = await repo.load_session("test-session-001")
        assert loaded is not None
        assert loaded.id == sample_session.id
        assert loaded.user_id == sample_session.user_id

    @pytest.mark.asyncio
    async def test_load_returns_none_for_missing(self, repo: StateRepositoryPort):
        loaded = await repo.load_session("nonexistent-id")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_update_session_status(self, repo: StateRepositoryPort, sample_session: Session):
        await repo.save_session(sample_session)
        await repo.update_session_status(sample_session.id, SessionStatus.RUNNING)
        loaded = await repo.load_session(sample_session.id)
        assert loaded is not None
        assert loaded.status == SessionStatus.RUNNING


class TestListSessions:
    """Session listing tests."""

    @pytest.mark.asyncio
    async def test_empty_when_no_sessions(self, repo: StateRepositoryPort):
        sessions = await repo.list_sessions()
        assert isinstance(sessions, list)

    @pytest.mark.asyncio
    async def test_lists_saved_sessions(self, repo: StateRepositoryPort):
        s1 = Session(id="s1", user_id="u1", status=SessionStatus.PENDING,
                     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        s2 = Session(id="s2", user_id="u1", status=SessionStatus.COMPLETED,
                     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        await repo.save_session(s1)
        await repo.save_session(s2)
        sessions = await repo.list_sessions()
        ids = [s.id for s in sessions]
        assert "s1" in ids
        assert "s2" in ids

    @pytest.mark.asyncio
    async def test_filter_by_user(self, repo: StateRepositoryPort):
        s1 = Session(id="s1", user_id="user-a", status=SessionStatus.PENDING,
                     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        s2 = Session(id="s2", user_id="user-b", status=SessionStatus.PENDING,
                     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        await repo.save_session(s1)
        await repo.save_session(s2)
        sessions_a = await repo.list_sessions(user_id="user-a")
        assert len(sessions_a) == 1
        assert sessions_a[0].id == "s1"


class TestDeleteSession:
    """Session deletion testing."""

    @pytest.mark.asyncio
    async def test_delete_removes_session(self, repo: StateRepositoryPort, sample_session: Session):
        await repo.save_session(sample_session)
        await repo.delete_session(sample_session.id)
        loaded = await repo.load_session(sample_session.id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_raise(self, repo: StateRepositoryPort):
        # Should not raise on deleting a session that doesn't exist
        await repo.delete_session("ghost-session")


class TestSessionLifecycle:
    """Complete session lifecycle: create -> run -> complete."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, repo: StateRepositoryPort):
        session = Session(
            id="lifecycle-test",
            user_id="tester",
            status=SessionStatus.PENDING,
        )
        await repo.save_session(session)
        loaded = await repo.load_session("lifecycle-test")
        assert loaded is not None and loaded.status == SessionStatus.PENDING

        await repo.update_session_status("lifecycle-test", SessionStatus.RUNNING)
        loaded = await repo.load_session("lifecycle-test")
        assert loaded is not None and loaded.status == SessionStatus.RUNNING

        await repo.update_session_status("lifecycle-test", SessionStatus.COMPLETED)
        loaded = await repo.load_session("lifecycle-test")
        assert loaded is not None and loaded.status == SessionStatus.COMPLETED
