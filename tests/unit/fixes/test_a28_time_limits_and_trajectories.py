"""A28: naive local job times, a listing limit that hid the oldest sessions from the
background jobs, and a trajectory consolidation that deleted every row when none qualified
as a keeper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.domain.models.session import SessionStatus
from weebot.domain.models.trajectory import TrajectorySummary


def test_job_times_are_timezone_aware():
    from weebot.scheduling.scheduler import ScheduledJob

    assert ScheduledJob(job_id="j", name="j").created_at.tzinfo is not None


class _PagedRepo:
    """Honours limit and offset like the SQLite repository; default limit is 100."""

    def __init__(self, count: int) -> None:
        self.sessions = [
            SimpleNamespace(id=f"s{i}", status=SessionStatus.RUNNING, updated_at=None)
            for i in range(count)
        ]
        self.loaded: list[str] = []

    async def list_sessions(self, limit: int = 100, offset: int = 0, **_kw):
        return self.sessions[offset : offset + limit]

    async def load_session(self, session_id: str):
        self.loaded.append(session_id)
        return SimpleNamespace(id=session_id)

    async def save_session(self, _session):
        return None


async def test_compaction_reaches_sessions_past_the_first_hundred(monkeypatch):
    from weebot.application.services import memory_compactor
    from weebot.scheduling import default_jobs

    class _Compactor:
        def compact_session(self, session):
            return session

    monkeypatch.setattr(memory_compactor, "MemoryCompactor", _Compactor)
    repo = _PagedRepo(150)
    await default_jobs._memory_compact_job(repo)
    assert len(repo.loaded) == 150


@pytest.mark.parametrize("keepers", [0])
async def test_consolidation_keeps_something_when_none_qualifies(tmp_path, keepers):
    from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository

    repo = TrajectoryRepository(str(tmp_path / "t.db"))
    for i in range(6):  # none has tool calls or tokens, so none is a "keeper"
        await repo.save(
            TrajectorySummary(task_id=f"t{i}", session_id="s", skill_name="k", score=i / 10)
        )
    await repo.consolidate_by_skill("k", min_count=5)
    pool = await repo._get_pool()
    rows = await pool.execute_read("SELECT id FROM trajectories WHERE skill_name = ?", ("k",))
    assert len(rows) >= 1
    del keepers


def test_a_job_row_written_before_the_fix_is_read_as_utc():
    from weebot.scheduling.scheduler import ScheduledJob

    job = ScheduledJob.from_dict(
        {"job_id": "j", "name": "j", "created_at": "2026-01-01T10:00:00", "last_run": None}
    )
    assert job.created_at.utcoffset().total_seconds() == 0


async def test_paging_stops_on_a_page_boundary(monkeypatch):
    from weebot.application.services import memory_compactor
    from weebot.scheduling import default_jobs

    class _Compactor:
        def compact_session(self, session):
            return session

    repo = _PagedRepo(1000)  # exactly two pages of 500
    monkeypatch.setattr(memory_compactor, "MemoryCompactor", _Compactor)
    await default_jobs._memory_compact_job(repo)
    assert len(repo.loaded) == 1000


async def test_consolidation_still_keeps_two_qualifying_trajectories(tmp_path):
    from weebot.infrastructure.persistence.trajectory_repo import TrajectoryRepository

    repo = TrajectoryRepository(str(tmp_path / "t.db"))
    for i in range(6):
        await repo.save(
            TrajectorySummary(
                task_id=f"t{i}", session_id="s", skill_name="k", score=i / 10,
                tool_call_count=1, total_tokens=10,
            )
        )
    assert await repo.consolidate_by_skill("k", min_count=5) == 4
