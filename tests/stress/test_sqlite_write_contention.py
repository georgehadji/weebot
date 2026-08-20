"""Stress tests — SQLite write contention under concurrent load.

Exercises the single-writer / multi-reader connection pool under increasing
concurrency to find the breaking point and measure latency degradation.

Run with:
    pytest tests/stress/test_sqlite_write_contention.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path

import pytest

from weebot.infrastructure.persistence.connection_pool import SQLiteConnectionPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_pool(db_path: Path, max_read: int = 5) -> SQLiteConnectionPool:
    pool = SQLiteConnectionPool(db_path, max_read_connections=max_read, enable_wal=True)
    await pool.initialize()
    async with pool.acquire_write() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS stress ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  worker INTEGER NOT NULL,"
            "  seq INTEGER NOT NULL,"
            "  payload TEXT NOT NULL,"
            "  ts REAL NOT NULL"
            ")"
        )
    return pool


async def _writer(
    pool: SQLiteConnectionPool, worker_id: int, n: int, latencies: list[float]
) -> int:
    """Write *n* rows, recording per-write latency. Returns rows written."""
    written = 0
    for seq in range(n):
        t0 = time.perf_counter()
        async with pool.acquire_write() as conn:
            await conn.execute(
                "INSERT INTO stress (worker, seq, payload, ts) VALUES (?, ?, ?, ?)",
                (worker_id, seq, f"data-{worker_id}-{seq}", time.time()),
            )
        latencies.append(time.perf_counter() - t0)
        written += 1
    return written


async def _reader(pool: SQLiteConnectionPool, duration: float, latencies: list[float]) -> int:
    """Read repeatedly for *duration* seconds, recording per-read latency. Returns read count."""
    reads = 0
    deadline = time.perf_counter() + duration
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        async with pool.acquire_read() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM stress")
            await cursor.fetchone()
            await cursor.close()
        latencies.append(time.perf_counter() - t0)
        reads += 1
        await asyncio.sleep(0)  # yield to let writers run
    return reads


def _report(label: str, latencies: list[float]) -> dict:
    if not latencies:
        return {"label": label, "count": 0}
    return {
        "label": label,
        "count": len(latencies),
        "p50_ms": round(statistics.median(latencies) * 1000, 2),
        "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)] * 1000, 2),
        "p99_ms": round(sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2),
        "max_ms": round(max(latencies) * 1000, 2),
        "mean_ms": round(statistics.mean(latencies) * 1000, 2),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWriteContention:
    """Concurrent writer stress on the single write connection."""

    @pytest.fixture(autouse=True)
    async def _pool(self, tmp_path):
        self.pool = await _setup_pool(tmp_path / "stress.db")
        yield
        await self.pool.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("concurrency", [1, 5, 10, 25, 50])
    async def test_concurrent_writers(self, concurrency: int):
        """Verify no 'database is locked' errors and latency stays bounded."""
        writes_per_worker = 20
        latencies: list[list[float]] = [[] for _ in range(concurrency)]

        tasks = [
            asyncio.create_task(_writer(self.pool, i, writes_per_worker, latencies[i]))
            for i in range(concurrency)
        ]
        results = await asyncio.gather(*tasks)

        total_written = sum(results)
        assert total_written == concurrency * writes_per_worker, "Some writes were lost"

        # Verify all rows exist
        async with self.pool.acquire_read() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM stress")
            row = await cursor.fetchone()
            await cursor.close()
        assert row[0] == total_written

        all_latencies = [l for worker in latencies for l in worker]
        report = _report(f"write-{concurrency}", all_latencies)

        # Latency assertion: p99 write should stay under 2s even at 50 writers.
        # SQLite write serialization means writers queue — but they shouldn't timeout.
        assert (
            report["p99_ms"] < 2000
        ), f"Write p99 latency {report['p99_ms']}ms exceeds 2s at concurrency={concurrency}"

    @pytest.mark.asyncio
    async def test_no_database_locked_errors(self):
        """50 writers × 50 writes each — no OperationalError should escape."""
        concurrency = 50
        writes_per_worker = 50
        errors: list[Exception] = []

        async def _safe_writer(wid: int):
            try:
                lats: list[float] = []
                await _writer(self.pool, wid, writes_per_worker, lats)
            except Exception as exc:
                errors.append(exc)

        await asyncio.gather(*[_safe_writer(i) for i in range(concurrency)])
        assert not errors, f"Got {len(errors)} errors: {errors[:5]}"


class TestReadWriteInteraction:
    """Readers must stay responsive during write storms."""

    @pytest.fixture(autouse=True)
    async def _pool(self, tmp_path):
        self.pool = await _setup_pool(tmp_path / "rw_stress.db", max_read=5)
        yield
        await self.pool.close()

    @pytest.mark.asyncio
    async def test_reads_unblocked_during_writes(self):
        """5 readers + 10 writers: read p95 should stay under 100ms."""
        write_latencies: list[list[float]] = [[] for _ in range(10)]
        read_latencies: list[list[float]] = [[] for _ in range(5)]

        writers = [
            asyncio.create_task(_writer(self.pool, i, 100, write_latencies[i])) for i in range(10)
        ]
        readers = [
            asyncio.create_task(_reader(self.pool, 3.0, read_latencies[i])) for i in range(5)
        ]

        await asyncio.gather(*writers, *readers)

        all_read = [l for r in read_latencies for l in r]
        report = _report("read-during-write", all_read)
        assert report["count"] > 0, "No reads completed"
        assert (
            report["p95_ms"] < 100
        ), f"Read p95 {report['p95_ms']}ms during write storm exceeds 100ms"

    @pytest.mark.asyncio
    async def test_read_pool_exhaustion_recovery(self):
        """6 concurrent readers with pool of 5 — 6th waits, all eventually succeed."""
        results: list[bool] = []

        async def _try_read(rid: int):
            try:
                async with self.pool.acquire_read() as conn:
                    await asyncio.sleep(0.1)  # hold the connection
                    cursor = await conn.execute("SELECT 1")
                    await cursor.fetchone()
                    await cursor.close()
                results.append(True)
            except TimeoutError:
                results.append(False)

        await asyncio.gather(*[_try_read(i) for i in range(6)])
        assert all(results), "Some readers timed out — pool didn't recover"


class TestWALBehavior:
    """WAL-specific stress scenarios."""

    @pytest.fixture(autouse=True)
    async def _pool(self, tmp_path):
        self.db_path = tmp_path / "wal_stress.db"
        self.pool = await _setup_pool(self.db_path)
        yield
        await self.pool.close()

    @pytest.mark.asyncio
    async def test_wal_file_bounded_under_sustained_writes(self):
        """1000 writes should not grow WAL unboundedly (autocheckpoint at 1000 pages)."""
        lats: list[float] = []
        await _writer(self.pool, 0, 1000, lats)

        wal_path = Path(str(self.db_path) + "-wal")
        if wal_path.exists():
            wal_size_kb = wal_path.stat().st_size / 1024
            # WAL should stay under 10 MB for 1000 small rows
            assert wal_size_kb < 10_240, f"WAL file is {wal_size_kb:.0f} KB — unbounded growth?"

    @pytest.mark.asyncio
    async def test_concurrent_writes_with_wal_checkpoint(self):
        """Writers + a manual checkpoint should not deadlock."""
        lats: list[float] = []
        writers = [asyncio.create_task(_writer(self.pool, i, 200, lats)) for i in range(5)]

        # Halfway through, trigger a checkpoint
        await asyncio.sleep(0.5)
        async with self.pool.acquire_write() as conn:
            await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

        await asyncio.gather(*writers)
        assert len(lats) == 1000  # 5 × 200


class TestPoolLifecycle:
    """Connection pool initialization, teardown, and error handling."""

    @pytest.mark.asyncio
    async def test_double_initialize_is_idempotent(self, tmp_path):
        pool = SQLiteConnectionPool(tmp_path / "idem.db")
        await pool.initialize()
        await pool.initialize()  # should not raise
        assert pool._initialized
        await pool.close()

    @pytest.mark.asyncio
    async def test_operations_after_close_raise(self, tmp_path):
        pool = SQLiteConnectionPool(tmp_path / "closed.db")
        await pool.initialize()
        await pool.close()

        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire_write() as _:
                pass

        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire_read() as _:
                pass

    @pytest.mark.asyncio
    async def test_write_rollback_on_error(self, tmp_path):
        pool = await _setup_pool(tmp_path / "rollback.db")
        try:
            # Insert a row successfully
            async with pool.acquire_write() as conn:
                await conn.execute(
                    "INSERT INTO stress (worker, seq, payload, ts) VALUES (0, 0, 'ok', 0)"
                )

            # Attempt a failing write
            with pytest.raises(Exception):
                async with pool.acquire_write() as conn:
                    await conn.execute(
                        "INSERT INTO stress (worker, seq, payload, ts) VALUES (0, 1, 'fail', 0)"
                    )
                    raise ValueError("simulated failure")

            # The failed row should have been rolled back
            async with pool.acquire_read() as conn:
                cursor = await conn.execute("SELECT COUNT(*) FROM stress")
                row = await cursor.fetchone()
                await cursor.close()
            assert row[0] == 1, "Rollback didn't work — partial write survived"
        finally:
            await pool.close()

    @pytest.mark.asyncio
    async def test_stats_reflect_pool_state(self, tmp_path):
        pool = SQLiteConnectionPool(tmp_path / "stats.db", max_read_connections=3)
        await pool.initialize()
        try:
            stats = pool.get_stats()
            assert stats["max_read_connections"] == 3
            assert stats["available_read_connections"] == 3
            assert stats["initialized"] is True
            assert stats["closed"] is False

            # Hold one read connection — available drops
            async with pool.acquire_read():
                stats = pool.get_stats()
                assert stats["available_read_connections"] == 2
        finally:
            await pool.close()
