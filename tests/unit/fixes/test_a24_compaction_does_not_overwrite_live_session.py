"""A24: the memory-compaction job loaded a RUNNING session, compacted it, and saved the stale
copy over the live row, losing whatever the running flow wrote in between. It now writes only
over the row it loaded (compare-and-swap) and skips the session when the row has moved."""

from __future__ import annotations

import copy

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

    async def save_session_if_unchanged(self, session, expected_updated_at) -> bool:
        if self.version[session.id] != self.loaded_version.get(session.id):
            return False
        await self.save_session(session)
        return True

    def flow_writes_meanwhile(self, session_id: str) -> None:
        self.version[session_id] += 1


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


async def test_compaction_still_saves_a_row_nobody_touched(monkeypatch):
    from weebot.application.services import memory_compactor
    from weebot.scheduling import default_jobs

    repo = _Repo()

    class _Compactor:
        def compact_session(self, session):
            return session.model_copy()

    monkeypatch.setattr(memory_compactor, "MemoryCompactor", _Compactor)
    await default_jobs._memory_compact_job(repo)
    assert repo.overwritten == [] and repo.version["s1"] == 1


async def test_sqlite_writes_only_over_the_row_it_was_given_the_time_of(tmp_path):
    from weebot.domain.models.event import MessageEvent
    from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

    repo = SQLiteStateRepository(db_path=str(tmp_path / "s.db"))
    try:
        await repo.save_session(Session(id="s1", user_id="u", agent_id="a"))
        loaded = await repo.load_session("s1")

        # A flow saves while the holder of `loaded` works.
        live = loaded.add_event(MessageEvent(role="assistant", message="newer"))
        await repo.save_session(live)

        stale = loaded.set_title("stale write")
        assert await repo.save_session_if_unchanged(stale, loaded.updated_at) is False
        kept = await repo.load_session("s1")
        assert [e.message for e in kept.events] == ["newer"] and kept.title != "stale write"

        fresh = kept.set_title("fresh write")
        assert await repo.save_session_if_unchanged(fresh, kept.updated_at) is True
        assert (await repo.load_session("s1")).title == "fresh write"
    finally:
        await repo.close()


async def test_a_deleted_row_is_not_resurrected():
    from weebot.infrastructure.persistence.in_memory_state_repo import InMemoryStateRepository

    repo = InMemoryStateRepository()
    gone = Session(id="s1", user_id="u", agent_id="a")
    assert await repo.save_session_if_unchanged(gone, gone.updated_at) is False
    assert await repo.load_session("s1") is None
