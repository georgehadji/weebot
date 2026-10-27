"""A24 repro (strict xfail until fixed): the memory-compaction job loaded a RUNNING session,
compacted it, and saved the stale copy over the live row, losing whatever the running flow
wrote in between."""

from __future__ import annotations

import copy

import pytest

from weebot.domain.models.session import Session, SessionStatus


class _Repo:
    """A store that notices a save made over a row that changed after it was loaded."""

    def __init__(self) -> None:
        self.rows = {"s1": Session(id="s1", user_id="u", agent_id="a", status=SessionStatus.RUNNING)}
        self.version = {"s1": 1}
        self.loaded_version: dict[str, int] = {}
        self.overwritten: list[str] = []

    async def list_sessions(self, limit: int = 100, offset: int = 0, **_kw):
        return list(self.rows.values())[offset : offset + limit]

    async def load_session(self, session_id: str):
        self.loaded_version[session_id] = self.version[session_id]
        return copy.deepcopy(self.rows[session_id])

    async def save_session(self, session):
        if self.version[session.id] != self.loaded_version.get(session.id):
            self.overwritten.append(session.id)
        self.rows[session.id] = session

    def flow_writes_meanwhile(self, session_id: str) -> None:
        self.version[session_id] += 1


@pytest.mark.xfail(strict=True, reason="A24: compaction saves a stale copy over a live row")
async def test_compaction_never_saves_over_a_row_that_changed_after_it_loaded(monkeypatch):
    from weebot.application.services import memory_compactor
    from weebot.scheduling import default_jobs

    repo = _Repo()

    class _Compactor:
        def compact_session(self, session):
            repo.flow_writes_meanwhile(session.id)  # the running flow saves while we compact
            return session.model_copy()

    monkeypatch.setattr(memory_compactor, "MemoryCompactor", _Compactor)
    await default_jobs._memory_compact_job(repo)
    assert repo.overwritten == []
