"""Async SQLite connection pool with WAL mode support."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

try:
    import aiosqlite
except ImportError:
    aiosqlite = None

logger = logging.getLogger(__name__)


class SQLiteConnectionPool:
    """
    Async connection pool for SQLite with WAL mode support.

    SQLite supports multiple concurrent readers but only a single writer.
    This pool maintains:
    - 1 dedicated write connection (exclusive)
    - N read connections (shared, poolable)

    WAL (Write-Ahead Logging) mode enables:
    - Readers don't block writers
    - Writers don't block readers
    - Better concurrency than default rollback journal

    Usage:
        pool = SQLiteConnectionPool("./data.db", max_read_connections=5)
        await pool.initialize()

        # For reads
        async with pool.acquire_read() as conn:
            rows = await conn.execute("SELECT * FROM table")
            ...

        # For writes
        async with pool.acquire_write() as conn:
            await conn.execute("INSERT INTO table ...")

        await pool.close()

    Attributes:
        db_path: Path to SQLite database file
        max_read_connections: Maximum concurrent read connections
        timeout: Maximum seconds to wait for a connection
    """

    def __init__(
        self,
        db_path: str | Path,
        max_read_connections: int = 5,
        timeout: float = 30.0,
        enable_wal: bool = True,
        close_drain_timeout: float = 5.0,
    ):
        """
        Initialize connection pool.

        Args:
            db_path: Path to SQLite database file
            max_read_connections: Maximum number of concurrent read connections
            timeout: Maximum seconds to wait for connection from pool
            enable_wal: Enable WAL mode for better concurrency
            close_drain_timeout: Seconds close() waits for in-flight users to
                finish before force-closing their connections. Deliberately far
                shorter than ``timeout``: a shutdown path must never inherit a
                request path's patience.
        """
        if aiosqlite is None:
            raise ImportError(
                "aiosqlite is required for connection pooling. "
                "Install with: pip install aiosqlite"
            )

        self.db_path = Path(db_path)
        self.max_read = max(max_read_connections, 1)
        self.timeout = timeout
        self.enable_wal = enable_wal
        self.close_drain_timeout = close_drain_timeout

        # Connections
        self._write_conn: aiosqlite.Connection | None = None
        self._read_pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        self._read_semaphore = asyncio.Semaphore(self.max_read)
        # Every read connection this pool has ever opened, queued or checked
        # out. close() used to work from the idle queue alone, which cannot see
        # a connection a reader is currently holding.
        self._read_conns: list[aiosqlite.Connection] = []

        # State
        self._initialized = False
        self._closed = False
        # Set the moment close() starts, so no new caller is admitted while the
        # pool drains. Distinct from _closed, which still means "close() has
        # finished and every connection is shut": a second close() must block
        # on _lock and wait rather than return early on a half-closed pool.
        self._closing = False
        self._lock = asyncio.Lock()
        # Serialises concurrent writers so they don't share an uncommitted
        # transaction on the single write connection (which would cause one
        # writer's failure to roll back another's uncommitted work).
        # WARNING: Never acquire _write_lock inside acquire_read() context
        # or vice versa — this creates a deadlock (single-writer/multi-reader).
        self._write_lock = asyncio.Lock()

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """
        Initialize the pool and create connections.

        This method:
        1. Creates the write connection
        2. Enables WAL mode (if configured)
        3. Pre-creates read connections
        """
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            logger.debug(f"Initializing SQLite pool for {self.db_path}")

            # Create write connection
            # Without timeout=, sqlite uses its 5s default busy timeout, so the
            # pool's configured value governed only the read-queue wait and never
            # the database itself: a writer blocked past 5s raised "database is
            # locked" no matter how generous self.timeout was.
            self._write_conn = await aiosqlite.connect(str(self.db_path), timeout=self.timeout)

            # Enable WAL mode for better concurrency
            if self.enable_wal:
                await self._write_conn.execute("PRAGMA journal_mode=WAL")
                await self._write_conn.execute("PRAGMA synchronous=NORMAL")
                # Checkpoint every 1000 pages to prevent WAL from growing too large
                await self._write_conn.execute("PRAGMA wal_autocheckpoint=1000")
                logger.debug("WAL mode enabled")

            await self._write_conn.commit()

            # Pre-create read connections
            for i in range(self.max_read):
                conn = await aiosqlite.connect(str(self.db_path), timeout=self.timeout)
                conn.row_factory = aiosqlite.Row
                self._read_conns.append(conn)
                await self._read_pool.put(conn)
                logger.debug(f"Created read connection {i+1}/{self.max_read}")

            self._initialized = True
            logger.info(
                f"SQLite pool initialized: {self.max_read} read connections, "
                f"WAL={self.enable_wal}"
            )

    @asynccontextmanager
    async def acquire_write(self):
        """
        Acquire the exclusive write connection.

        Yields:
            aiosqlite.Connection: Write connection

        Raises:
            RuntimeError: If pool is closed
        """
        if self._closed or self._closing:
            raise RuntimeError("Connection pool is closed")

        if not self._initialized:
            await self.initialize()

        if self._write_conn is None:
            raise RuntimeError("Write connection not initialized")

        # Serialise all writers: SQLite has one write connection; without this
        # lock two concurrent coroutines would share the same open transaction
        # and one writer's rollback (or lack thereof) would corrupt the other's
        # work.
        async with self._write_lock:
            try:
                yield self._write_conn
            except Exception:
                # Roll back any partial work so the connection is left in a
                # clean state for the next writer.
                try:
                    await self._write_conn.rollback()
                except Exception:
                    pass
                raise
            else:
                await self._write_conn.commit()

    @asynccontextmanager
    async def acquire_read(self):
        """
        Acquire a read connection from the pool.

        Yields:
            aiosqlite.Connection: Read connection

        Raises:
            RuntimeError: If pool is closed
            asyncio.TimeoutError: If no connection available within timeout
        """
        if self._closed or self._closing:
            raise RuntimeError("Connection pool is closed")

        if not self._initialized:
            await self.initialize()

        async with self._read_semaphore:
            # Wait for available connection with timeout
            try:
                conn = await asyncio.wait_for(self._read_pool.get(), timeout=self.timeout)
            except TimeoutError:
                raise TimeoutError(f"Timeout waiting for read connection ({self.timeout}s)")

            try:
                yield conn
            finally:
                if self._closed:
                    # close() ran while this reader held the connection. Putting
                    # it back would park a live connection — and its non-daemon
                    # aiosqlite worker thread — on a queue nothing will ever
                    # drain again. close() force-closes what it could not reach,
                    # so there is nothing left to return it to.
                    logger.debug(
                        "Read connection released after pool close; not re-queued"
                    )
                else:
                    # Return connection to pool
                    await self._read_pool.put(conn)

    async def execute_write(self, sql: str, parameters: tuple | None = None) -> None:
        """
        Execute a write query.

        Convenience method for simple writes without explicit transaction handling.

        Args:
            sql: SQL statement to execute
            parameters: Query parameters
        """
        async with self.acquire_write() as conn:
            await conn.execute(sql, parameters or ())

    async def execute_read(
        self, sql: str, parameters: tuple | None = None, fetch_all: bool = True
    ) -> list | tuple | None:
        """
        Execute a read query.

        Convenience method for simple reads.

        Args:
            sql: SQL SELECT statement
            parameters: Query parameters
            fetch_all: If True, return all rows; otherwise return first row

        Returns:
            List of rows if fetch_all=True, single row or None otherwise
        """
        async with self.acquire_read() as conn:
            cursor = await conn.execute(sql, parameters or ())
            if fetch_all:
                rows = await cursor.fetchall()
                await cursor.close()
                return rows
            else:
                row = await cursor.fetchone()
                await cursor.close()
                return row

    async def close(self) -> None:
        """
        Close all connections and clean up.

        This should be called during application shutdown.
        """
        if self._closed:
            return

        async with self._lock:
            if self._closed:
                return

            logger.debug("Closing SQLite connection pool")

            # ── Stop admitting new users, then drain the ones in flight ──
            #
            # close() used to go straight to the idle queue, which by
            # construction cannot see a connection a reader is currently
            # holding. Measured on a 3-reader pool with one reader mid-request:
            # close() reported success, one aiosqlite worker thread was still
            # alive, the leaked connection still served queries, and the reader
            # then returned it to a queue nothing would drain again. Those
            # worker threads are plain non-daemon threads (aiosqlite 0.22.1
            # `Thread(target=_connection_worker_thread)`), so a process holding
            # any reference to the pool hung forever in `threading._shutdown()`
            # — a 20s timeout had to kill it.
            #
            # Closing the gate first means the drain waits only for users
            # already in flight. Acquiring every read slot then proves no
            # reader holds a connection, and taking the write lock proves no
            # writer is mid-transaction. Both waits are bounded by
            # close_drain_timeout, not by self.timeout: a shutdown that waits
            # 30s per connection is its own failure. Whatever the drain does
            # not win is force-closed below, so close() never returns with a
            # connection still open.
            self._closing = True
            drained = await self._drain(self.close_drain_timeout)

            # Close write connection
            if self._write_conn:
                try:
                    # Checkpoint WAL before closing. This can fail on a corrupt
                    # database — guard it separately so a checkpoint failure never
                    # prevents the connection (and its aiosqlite worker thread)
                    # from being closed below. Leaving the thread alive hangs the
                    # interpreter at shutdown (it is a non-daemon thread).
                    if self.enable_wal:
                        try:
                            await self._write_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        except Exception as e:
                            logger.warning(f"WAL checkpoint failed during close: {e}")
                    await self._write_conn.close()
                    logger.debug("Write connection closed")
                except Exception as e:
                    logger.warning(f"Error closing write connection: {e}")
                finally:
                    self._write_conn = None

            # Close every read connection this pool opened — not merely the
            # ones that happen to be sitting in the idle queue.
            closed_count = 0
            for conn in self._read_conns:
                try:
                    await conn.close()
                    closed_count += 1
                except Exception as e:
                    logger.warning(f"Error closing read connection: {e}")
            self._read_conns.clear()
            while not self._read_pool.empty():
                self._read_pool.get_nowait()

            logger.debug(f"Closed {closed_count} read connections")

            self._closed = True
            self._initialized = False
            if drained:
                logger.info("SQLite connection pool closed")
            else:
                logger.warning(
                    "SQLite connection pool closed after force-closing connections still "
                    "in use — in-flight queries on %s were interrupted",
                    self.db_path,
                )

    async def _drain(self, timeout: float) -> bool:
        """Wait for in-flight readers and the writer to finish.

        Returns True if every user finished within ``timeout``. A False return
        is not a failure to handle — it is the signal that the connections
        closed next are being taken from someone.
        """
        acquired: list[asyncio.Semaphore | asyncio.Lock] = []
        try:
            async with asyncio.timeout(timeout):
                for _ in range(self.max_read):
                    await self._read_semaphore.acquire()
                    acquired.append(self._read_semaphore)
                await self._write_lock.acquire()
                acquired.append(self._write_lock)
            return True
        except TimeoutError:
            logger.warning(
                "Pool for %s still had users after %.1fs; closing their connections anyway",
                self.db_path,
                timeout,
            )
            return False
        finally:
            # Release whatever was taken. Holding these past close() would
            # deadlock any caller that has not yet noticed the pool is gone.
            for primitive in acquired:
                primitive.release()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    def get_stats(self) -> dict:
        """
        Get pool statistics.

        Returns:
            Dictionary with pool statistics
        """
        return {
            "db_path": str(self.db_path),
            "max_read_connections": self.max_read,
            "available_read_connections": self._read_pool.qsize(),
            "initialized": self._initialized,
            "closed": self._closed,
            "closing": self._closing,
            "wal_enabled": self.enable_wal,
        }


# Singleton pool registry for reuse across repositories
_pool_registry: dict[str, SQLiteConnectionPool] = {}
_pool_lock: asyncio.Lock | None = None


def _get_pool_lock() -> asyncio.Lock:
    """Return the module-level pool lock, creating it lazily within the running loop."""
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def get_or_create_pool(
    db_path: str | Path, max_read_connections: int = 5, **kwargs
) -> SQLiteConnectionPool:
    """
    Get existing pool or create new one for the given database path.

    This allows multiple repositories to share the same connection pool
    for the same database file.

    Args:
        db_path: Path to SQLite database
        max_read_connections: Maximum read connections
        **kwargs: Additional arguments for pool creation

    Returns:
        SQLiteConnectionPool instance
    """
    path_key = str(Path(db_path).resolve())

    async with _get_pool_lock():
        existing = _pool_registry.get(path_key)
        if existing is not None and existing._closed:
            # close() does not evict from the registry, so a registry hit can be a
            # dead pool -- and every repository close() calls pool.close() directly.
            # Returning it made the *next* caller fail with "Connection pool is
            # closed" on an object it had just been handed as ready to use.
            logger.info(f"Replacing closed pool for {db_path}")
            del _pool_registry[path_key]
            existing = None

        if existing is None:
            pool = SQLiteConnectionPool(
                db_path=db_path, max_read_connections=max_read_connections, **kwargs
            )
            await pool.initialize()
            _pool_registry[path_key] = pool
            logger.info(f"Created new pool for {db_path}")

        return _pool_registry[path_key]


async def close_all_pools() -> None:
    """Close all registered connection pools."""
    global _pool_registry

    async with _get_pool_lock():
        for path, pool in list(_pool_registry.items()):
            try:
                await pool.close()
                logger.debug(f"Closed pool for {path}")
            except Exception as e:
                logger.warning(f"Error closing pool for {path}: {e}")

        _pool_registry.clear()
        logger.info("All connection pools closed")
