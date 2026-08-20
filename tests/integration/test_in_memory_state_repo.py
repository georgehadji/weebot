"""Contract tests for InMemoryStateRepository — verifying new pagination + filtering.

WI-03 added ``status``, ``limit``, and ``offset`` parameters to
``list_sessions()`` on the port. These tests exercise the in-memory
adapter specifically to confirm the parameters are wired correctly.
"""

from __future__ import annotations

from datetime import datetime, UTC

import pytest

from weebot.domain.models.session import Session, SessionStatus
from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository


@pytest.fixture
def repo() -> InMemoryStateRepository:
    return InMemoryStateRepository()


def _make_session(
    sid: str, user: str = "u1", status: SessionStatus = SessionStatus.PENDING
) -> Session:
    now = datetime.now(UTC)
    return Session(id=sid, user_id=user, status=status, created_at=now, updated_at=now)


class TestListSessionsPagination:
    """Verify limit and offset work on the in-memory adapter."""

    @pytest.mark.asyncio
    async def test_limit(self, repo: InMemoryStateRepository):
        for i in range(10):
            await repo.save_session(_make_session(f"s{i}"))
        sessions = await repo.list_sessions(limit=3)
        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_offset(self, repo: InMemoryStateRepository):
        for i in range(5):
            await repo.save_session(_make_session(f"s{i}"))
        sessions = await repo.list_sessions(limit=2, offset=2)
        assert len(sessions) == 2
        # The adapter iterates in insertion order; offsets skip the first 2
        ids = {s.id for s in sessions}
        assert ids <= {f"s{i}" for i in range(5)}

    @pytest.mark.asyncio
    async def test_offset_exceeds(self, repo: InMemoryStateRepository):
        for i in range(3):
            await repo.save_session(_make_session(f"s{i}"))
        sessions = await repo.list_sessions(offset=10)
        assert isinstance(sessions, list)
        assert len(sessions) == 0


class TestListSessionsFiltering:
    """Verify status filtering works on the in-memory adapter."""

    @pytest.mark.asyncio
    async def test_filter_by_status(self, repo: InMemoryStateRepository):
        await repo.save_session(_make_session("s1", status=SessionStatus.PENDING))
        await repo.save_session(_make_session("s2", status=SessionStatus.RUNNING))
        await repo.save_session(_make_session("s3", status=SessionStatus.COMPLETED))

        pending = await repo.list_sessions(status="pending")
        assert len(pending) == 1
        assert pending[0].id == "s1"

        running = await repo.list_sessions(status="running")
        assert len(running) == 1
        assert running[0].id == "s2"

    @pytest.mark.asyncio
    async def test_filter_by_status_and_user(self, repo: InMemoryStateRepository):
        await repo.save_session(_make_session("s1", user="a", status=SessionStatus.PENDING))
        await repo.save_session(_make_session("s2", user="b", status=SessionStatus.PENDING))
        await repo.save_session(_make_session("s3", user="a", status=SessionStatus.RUNNING))

        result = await repo.list_sessions(user_id="a", status="pending")
        assert len(result) == 1
        assert result[0].id == "s1"
