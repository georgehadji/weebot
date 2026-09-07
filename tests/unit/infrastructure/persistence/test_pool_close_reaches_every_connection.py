"""close() must reach connections that are checked out, not just idle ones.

D36. `SQLiteConnectionPool.close()` drained `self._read_pool` — the idle queue —
which by construction cannot see a connection a reader is currently holding.

Measured before the fix, on a 3-reader pool with one reader mid-request:
close() logged "SQLite connection pool closed", one aiosqlite worker thread was
still alive, the leaked connection still answered `SELECT 1`, and the reader
then returned it to a queue nothing would ever drain again. aiosqlite 0.22.1
runs one plain `Thread(target=_connection_worker_thread)` per connection with
`daemon=False`, so any process still referencing the pool — the module-level
`_pool_registry` does exactly that — hung in `threading._shutdown()` at exit. A
20-second timeout had to kill it; after the fix the same script exits in 6.

close() now closes the gate, drains in-flight users under a bounded timeout,
and force-closes whatever the drain does not win.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from aiosqlite.core import _connection_worker_thread

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool


def _worker_threads() -> list[threading.Thread]:
    return [
        t
        for t in threading.enumerate()
        if getattr(t, "_target", None) is _connection_worker_thread
    ]


@pytest.mark.asyncio
async def test_a_checked_out_connection_is_closed_too(tmp_path):
    pool = SQLiteConnectionPool(tmp_path / "d.db", max_read_connections=3, close_drain_timeout=0.2)
    await pool.initialize()
    before = len(_worker_threads())
    assert before >= 4, "1 write + 3 read connections expected"

    entered, release = asyncio.Event(), asyncio.Event()
    held: list = []

    async def reader():
        async with pool.acquire_read() as conn:
            held.append(conn)
            entered.set()
            await release.wait()

    task = asyncio.create_task(reader())
    await entered.wait()
    assert pool._read_pool.qsize() == 2, "the held connection is not in the idle queue"

    await pool.close()
    try:
        assert len(_worker_threads()) == before - 4, (
            "close() left a worker thread alive: the connection a reader held was "
            "never closed, and that thread is non-daemon, so the interpreter will "
            "block on it at exit"
        )
        with pytest.raises(Exception):
            await held[0].execute("SELECT 1")
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_a_released_connection_is_not_requeued_onto_a_closed_pool(tmp_path):
    pool = SQLiteConnectionPool(tmp_path / "d.db", max_read_connections=2, close_drain_timeout=0.2)
    await pool.initialize()

    entered, release = asyncio.Event(), asyncio.Event()

    async def reader():
        async with pool.acquire_read() as conn:
            entered.set()
            await release.wait()

    task = asyncio.create_task(reader())
    await entered.wait()
    await pool.close()
    release.set()
    await task

    assert pool._read_pool.qsize() == 0, (
        "a live connection was parked on the idle queue of a closed pool, where "
        "nothing will ever drain it"
    )


@pytest.mark.asyncio
async def test_close_waits_for_a_reader_that_finishes_in_time(tmp_path, caplog):
    """The graceful path: no interruption, no warning."""
    pool = SQLiteConnectionPool(tmp_path / "d.db", max_read_connections=2, close_drain_timeout=5.0)
    await pool.initialize()

    finished = asyncio.Event()

    async def reader():
        async with pool.acquire_read() as conn:
            await asyncio.sleep(0.05)
            await conn.execute("SELECT 1")
        finished.set()

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)  # let the reader check the connection out
    await pool.close()

    await task
    assert finished.is_set(), "the reader was cut off instead of being waited for"
    assert not [r for r in caplog.records if "force-closing" in r.getMessage()], (
        "a reader that finished within the drain window should not be reported as "
        "force-closed"
    )


@pytest.mark.asyncio
async def test_close_does_not_wait_forever_on_a_stuck_reader(tmp_path):
    """Bounded: a shutdown path must not inherit a request path's patience."""
    pool = SQLiteConnectionPool(
        tmp_path / "d.db", max_read_connections=2, timeout=30.0, close_drain_timeout=0.2
    )
    await pool.initialize()

    entered, release = asyncio.Event(), asyncio.Event()

    async def stuck():
        async with pool.acquire_read():
            entered.set()
            await release.wait()

    task = asyncio.create_task(stuck())
    await entered.wait()

    started = asyncio.get_running_loop().time()
    await pool.close()
    elapsed = asyncio.get_running_loop().time() - started

    release.set()
    await task
    assert elapsed < 5.0, f"close() waited {elapsed:.1f}s; the drain bound is 0.2s, not timeout=30s"


@pytest.mark.asyncio
async def test_a_closing_pool_admits_no_new_users(tmp_path):
    pool = SQLiteConnectionPool(tmp_path / "d.db", max_read_connections=2, close_drain_timeout=0.2)
    await pool.initialize()
    await pool.close()

    with pytest.raises(RuntimeError, match="closed"):
        async with pool.acquire_read():
            pass
    with pytest.raises(RuntimeError, match="closed"):
        async with pool.acquire_write():
            pass


@pytest.mark.asyncio
async def test_close_is_idempotent_and_still_works_with_no_readers(tmp_path):
    pool = SQLiteConnectionPool(tmp_path / "d.db", max_read_connections=2, close_drain_timeout=0.2)
    await pool.initialize()
    before = len(_worker_threads())
    await pool.close()
    await pool.close()
    assert len(_worker_threads()) == before - 3
