"""A15: a writer cancelled mid-transaction must not leave its rows for the next writer to commit."""

from __future__ import annotations

import asyncio

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool


async def test_a_cancelled_writer_leaves_no_rows_behind(tmp_path):
    pool = SQLiteConnectionPool(tmp_path / "p.db")
    await pool.initialize()
    try:
        async with pool.acquire_write() as conn:
            await conn.execute("CREATE TABLE t (v TEXT)")
        inside = asyncio.Event()

        async def cancelled_writer():
            async with pool.acquire_write() as conn:
                await conn.execute("INSERT INTO t VALUES ('ghost')")
                inside.set()
                await asyncio.sleep(60)

        task = asyncio.create_task(cancelled_writer())
        await inside.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        async with pool.acquire_write() as conn:
            await conn.execute("INSERT INTO t VALUES ('real')")
        async with pool.acquire_read() as conn:
            rows = await (await conn.execute("SELECT v FROM t ORDER BY v")).fetchall()
        assert [r[0] for r in rows] == ["real"]
    finally:
        await pool.close()
