"""Async SQLite connection pool with WAL mode support."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

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
    ):
        """
        Initialize connection pool.
        
        Args:
            db_path: Path to SQLite database file
            max_read_connections: Maximum number of concurrent read connections
            timeout: Maximum seconds to wait for connection from pool
            enable_wal: Enable WAL mode for better concurrency
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
        
        # Connections
        self._write_conn: Optional[aiosqlite.Connection] = None
        self._read_pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()
        self._read_semaphore = asyncio.Semaphore(self.max_read)

        # State
        self._initialized = False
        self._closed = False
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
            self._write_conn = await aiosqlite.connect(str(self.db_path))
            
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
                conn = await aiosqlite.connect(str(self.db_path))
                conn.row_factory = aiosqlite.Row
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
        if self._closed:
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
        if self._closed:
            raise RuntimeError("Connection pool is closed")
        
        if not self._initialized:
            await self.initialize()
        
        async with self._read_semaphore:
            # Wait for available connection with timeout
            try:
                conn = await asyncio.wait_for(
                    self._read_pool.get(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(
                    f"Timeout waiting for read connection ({self.timeout}s)"
                )
            
            try:
                yield conn
            finally:
                # Return connection to pool
                await self._read_pool.put(conn)
    
    async def execute_write(self, sql: str, parameters: Optional[tuple] = None) -> None:
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
        self,
        sql: str,
        parameters: Optional[tuple] = None,
        fetch_all: bool = True
    ) -> list | Optional[tuple]:
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
            
            # Close write connection
            if self._write_conn:
                try:
                    # Checkpoint WAL before closing
                    if self.enable_wal:
                        await self._write_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    await self._write_conn.close()
                    logger.debug("Write connection closed")
                except Exception as e:
                    logger.warning(f"Error closing write connection: {e}")
                finally:
                    self._write_conn = None
            
            # Close all read connections in pool
            closed_count = 0
            while not self._read_pool.empty():
                try:
                    conn = await self._read_pool.get()
                    await conn.close()
                    closed_count += 1
                except Exception as e:
                    logger.warning(f"Error closing read connection: {e}")
            
            logger.debug(f"Closed {closed_count} read connections")
            
            self._closed = True
            self._initialized = False
            logger.info("SQLite connection pool closed")
    
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
            "wal_enabled": self.enable_wal,
        }


# Singleton pool registry for reuse across repositories
_pool_registry: dict[str, SQLiteConnectionPool] = {}
_pool_lock = asyncio.Lock()


async def get_or_create_pool(
    db_path: str | Path,
    max_read_connections: int = 5,
    **kwargs
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
    
    async with _pool_lock:
        if path_key not in _pool_registry:
            pool = SQLiteConnectionPool(
                db_path=db_path,
                max_read_connections=max_read_connections,
                **kwargs
            )
            await pool.initialize()
            _pool_registry[path_key] = pool
            logger.info(f"Created new pool for {db_path}")
        
        return _pool_registry[path_key]


async def close_all_pools() -> None:
    """Close all registered connection pools."""
    global _pool_registry
    
    async with _pool_lock:
        for path, pool in list(_pool_registry.items()):
            try:
                await pool.close()
                logger.debug(f"Closed pool for {path}")
            except Exception as e:
                logger.warning(f"Error closing pool for {path}: {e}")
        
        _pool_registry.clear()
        logger.info("All connection pools closed")
