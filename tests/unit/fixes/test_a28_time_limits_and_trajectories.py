"""A28 repros (strict xfail until fixed): naive local job times, a listing limit that hides the
oldest sessions from the background jobs, and a trajectory consolidation that deletes every
row when none qualifies as a keeper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from weebot.domain.models.session import SessionStatus
from weebot.domain.models.trajectory import TrajectorySummary


@pytest.mark.xfail(strict=True, reason="A28: job times are naive local datetimes")
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


@pytest.mark.xfail(strict=True, reason="A28: list_sessions default limit 100")
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
@pytest.mark.xfail(strict=True, reason="A28: consolidation deletes every row")
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
