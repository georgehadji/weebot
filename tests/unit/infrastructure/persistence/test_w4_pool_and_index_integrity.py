"""Wave 4 of the V7 defect hunt — persistence lifecycle and index integrity.

Four defects, each proven by an executable trigger against a real sqlite file:

* ``get_or_create_pool`` handed back pools that had already been closed.
  ``close()`` sets ``_closed`` but does not evict from ``_pool_registry``, and
  every repository ``close()`` calls ``pool.close()`` directly -- so the next
  caller received an object presented as ready to use whose every operation
  raised ``RuntimeError: Connection pool is closed``.
* The pool's configured ``timeout`` never reached sqlite. It governed only the
  read-queue wait, so writers used sqlite's 5s default busy timeout no matter
  what the pool was configured with.
* The FTS5 watermark advanced to ``len(session.events)`` whether or not
  ``index_event`` raised, so an event that failed to index was never retried
  and stayed permanently absent from search.
* ``PERSISTENCE_RETRY_CONFIG`` left ``retryable`` unset, which the backoff
  helper treats as "retry everything" -- so a permanently-invalid session burned
  every delay before dead-lettering.
"""

from __future__ import annotations

import sqlite3

import pytest

import weebot.infrastructure.persistence.connection_pool as cp


@pytest.fixture
def clean_registry():
    """The pool registry is module-level; keep tests from leaking into each other."""
    saved = dict(cp._pool_registry)
    cp._pool_registry.clear()
    yield
    cp._pool_registry.clear()
    cp._pool_registry.update(saved)


class TestClosedPoolsAreNeverHandedOut:
    @pytest.mark.asyncio
    async def test_pool_after_close_is_usable(self, tmp_path, clean_registry):
        db = tmp_path / "sessions.db"

        first = await cp.get_or_create_pool(str(db))
        await first.close()

        second = await cp.get_or_create_pool(str(db))

        assert second is not first
        assert second._closed is False
        await second.execute_read("SELECT 1")  # must not raise
        await second.close()

    @pytest.mark.asyncio
    async def test_repeated_close_reopen_cycles(self, tmp_path, clean_registry):
        db = tmp_path / "sessions.db"

        for _ in range(5):
            pool = await cp.get_or_create_pool(str(db))
            assert pool._closed is False
            await pool.execute_read("SELECT 1")
            await pool.close()

    @pytest.mark.asyncio
    async def test_live_pool_is_still_shared(self, tmp_path, clean_registry):
        """No-regression: the registry must still return one pool per path."""
        db = tmp_path / "sessions.db"

        a = await cp.get_or_create_pool(str(db))
        b = await cp.get_or_create_pool(str(db))

        assert a is b
        await a.close()

    @pytest.mark.asyncio
    async def test_distinct_paths_get_distinct_pools(self, tmp_path, clean_registry):
        a = await cp.get_or_create_pool(str(tmp_path / "one.db"))
        b = await cp.get_or_create_pool(str(tmp_path / "two.db"))

        assert a is not b
        await cp.close_all_pools()


class TestConfiguredTimeoutReachesSqlite:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("timeout", [5.0, 30.0])
    async def test_busy_timeout_matches_pool_timeout(self, tmp_path, timeout, clean_registry):
        pool = cp.SQLiteConnectionPool(db_path=str(tmp_path / "t.db"), timeout=timeout)
        await pool.initialize()
        try:
            async with pool.acquire_write() as conn:
                cursor = await conn.execute("PRAGMA busy_timeout")
                row = await cursor.fetchone()
                await cursor.close()
            assert row[0] == int(timeout * 1000)
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_read_connections_carry_it_too(self, tmp_path, clean_registry):
        pool = cp.SQLiteConnectionPool(db_path=str(tmp_path / "t.db"), timeout=17.0)
        await pool.initialize()
        try:
            async with pool.acquire_read() as conn:
                cursor = await conn.execute("PRAGMA busy_timeout")
                row = await cursor.fetchone()
                await cursor.close()
            assert row[0] == 17000
        finally:
            await pool.close()


class TestRetryPolicyDistinguishesPermanentErrors:
    def test_permanent_errors_are_not_retried(self):
        from weebot.infrastructure.persistence.session_persistence_adapter import (
            PERSISTENCE_RETRY_CONFIG,
        )

        assert PERSISTENCE_RETRY_CONFIG.retryable is not None
        for exc in (
            ValueError("bad session"),
            TypeError("wrong shape"),
            AttributeError("no such field"),
            KeyError("missing"),
            sqlite3.IntegrityError("UNIQUE constraint failed"),
            sqlite3.ProgrammingError("wrong number of bindings"),
        ):
            assert PERSISTENCE_RETRY_CONFIG.retryable(exc) is False, exc

    def test_transient_errors_are_still_retried(self):
        from weebot.infrastructure.persistence.session_persistence_adapter import (
            PERSISTENCE_RETRY_CONFIG,
        )

        for exc in (
            sqlite3.OperationalError("database is locked"),
            OSError("disk busy"),
            TimeoutError("slow"),
            RuntimeError("something odd"),  # unknown => still retried, by design
        ):
            assert PERSISTENCE_RETRY_CONFIG.retryable(exc) is True, exc

    def test_pydantic_validation_error_is_permanent(self):
        """ValidationError subclasses ValueError, so it must be covered."""
        from pydantic import BaseModel, ValidationError

        from weebot.infrastructure.persistence.session_persistence_adapter import (
            PERSISTENCE_RETRY_CONFIG,
        )

        class M(BaseModel):
            x: int

        try:
            M(x="not an int")
        except ValidationError as exc:
            assert PERSISTENCE_RETRY_CONFIG.retryable(exc) is False
        else:  # pragma: no cover
            pytest.fail("expected a ValidationError")


class TestFts5WatermarkTracksWhatWasIndexed:
    """The watermark is the only record of which events reached the index.

    It used to advance to len(session.events) unconditionally, so an event whose
    index_event() call raised was logged, stepped over, and never retried -- its
    content permanently unsearchable while the repo believed it was indexed.
    """

    @staticmethod
    async def _repo(tmp_path):
        from weebot.infrastructure.persistence.sqlite_state_repo import SQLiteStateRepository

        return SQLiteStateRepository(db_path=str(tmp_path / "sessions.db"))

    @staticmethod
    def _session(n_events: int):
        from weebot.domain.models.event import MessageEvent
        from weebot.domain.models.session import Session

        session = Session(id="s-fts")
        for i in range(n_events):
            session.events.append(MessageEvent(role="user", message=f"event {i}"))
        return session

    @pytest.mark.asyncio
    async def test_watermark_does_not_pass_a_failed_event(
        self, tmp_path, monkeypatch, clean_registry
    ):
        import weebot.infrastructure.persistence.sqlite_state_repo as mod

        calls = {"n": 0}

        async def failing_index_event(conn, session_id, event_type, summary, content):
            calls["n"] += 1
            if calls["n"] == 3:  # the third event cannot be indexed
                raise sqlite3.OperationalError("fts5 index unavailable")

        monkeypatch.setattr(mod, "index_event", failing_index_event)

        repo = await self._repo(tmp_path)
        session = self._session(5)
        try:
            await repo.save_session(session)

            # Two events indexed before the failure; the watermark must stop there
            # so the third is retried, not skipped.
            assert repo._fts5_indexed[session.id] == 2
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_failed_event_is_retried_on_the_next_save(
        self, tmp_path, monkeypatch, clean_registry
    ):
        import weebot.infrastructure.persistence.sqlite_state_repo as mod

        state = {"fail": True}
        indexed: list[str] = []

        async def flaky_index_event(conn, session_id, event_type, summary, content):
            if state["fail"]:
                raise sqlite3.OperationalError("fts5 index unavailable")
            indexed.append(summary)

        monkeypatch.setattr(mod, "index_event", flaky_index_event)

        repo = await self._repo(tmp_path)
        session = self._session(3)
        try:
            await repo.save_session(session)
            assert repo._fts5_indexed[session.id] == 0
            assert indexed == []

            state["fail"] = False
            await repo.save_session(session)

            assert repo._fts5_indexed[session.id] == 3
            assert indexed == ["event 0", "event 1", "event 2"]
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_clean_run_indexes_everything_once(
        self, tmp_path, monkeypatch, clean_registry
    ):
        """No-regression: with no failures the watermark still reaches the end."""
        import weebot.infrastructure.persistence.sqlite_state_repo as mod

        indexed: list[str] = []

        async def ok_index_event(conn, session_id, event_type, summary, content):
            indexed.append(summary)

        monkeypatch.setattr(mod, "index_event", ok_index_event)

        repo = await self._repo(tmp_path)
        session = self._session(4)
        try:
            await repo.save_session(session)
            assert repo._fts5_indexed[session.id] == 4
            assert len(indexed) == 4

            await repo.save_session(session)  # nothing new to index
            assert len(indexed) == 4
        finally:
            await repo.close()
