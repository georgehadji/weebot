"""PostgreSQL connection pool management — per-domain pools.

Each domain gets its own connection pool so a schema migration for one
domain never locks the others.  All pools use the same PostgreSQL server
but different database names (or schemas).

The DSN comes from ``WEEBOT_PG_DSN`` through SecretAccessor, read when the first
pool is built. There is no default: a built-in ``weebot:weebot`` DSN used to be
the fallback, and an empty ``WEEBOT_PG_DSN`` in ``.env`` overrode it anyway.
JSON and JSONB columns are encoded and decoded as Python values on every
connection, so callers pass dicts, not JSON strings.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

# Per-domain database names (appended to base DSN)
_DOMAIN_DATABASES = {
    "sessions": "weebot_sessions",
    "skills": "weebot_skills",
    "cache": "weebot_cache",
}

# Global pool cache: domain -> (event loop, pool). A pool only works on the loop that
# built it, so a second asyncio.run in the same process builds a fresh one. One lock
# per loop so two first callers cannot build two pools.
_pools: dict[str, tuple[Any, Any]] = {}
_pool_lock: asyncio.Lock | None = None
_lock_loop: Any = None


def _base_dsn() -> str:
    from weebot.config.secret_accessor import SecretAccessor

    dsn = SecretAccessor.get("WEEBOT_PG_DSN")
    if not dsn:
        raise RuntimeError(
            "WEEBOT_DB_BACKEND=postgresql needs WEEBOT_PG_DSN "
            "(postgresql://user:password@host:5432/weebot_sessions)"
        )
    return dsn


def _build_dsn(base_dsn: str, domain_db: str) -> str:
    """Replace the database name in *base_dsn* with *domain_db*."""
    return re.sub(r"/([^/?]+)(\?|$)", rf"/{domain_db}\2", base_dsn, count=1)


async def _init_connection(conn: Any) -> None:
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def get_pool(domain: str = "sessions", min_size: int = 2, max_size: int = 10) -> Any:
    """Return an asyncpg connection pool for *domain*.

    Pools are cached globally so repeated calls return the same pool.
    """
    global _pool_lock, _lock_loop
    import asyncpg

    if domain not in _DOMAIN_DATABASES:
        raise ValueError(f"Unknown domain {domain!r}. Choose from {list(_DOMAIN_DATABASES)}")
    loop = asyncio.get_running_loop()
    cached = _pools.get(domain)
    if cached is not None and cached[0] is loop:
        return cached[1]
    if _pool_lock is None or _lock_loop is not loop:
        _pool_lock, _lock_loop = asyncio.Lock(), loop
    async with _pool_lock:
        cached = _pools.get(domain)
        if cached is None or cached[0] is not loop:
            pool = await asyncpg.create_pool(
                dsn=_build_dsn(_base_dsn(), _DOMAIN_DATABASES[domain]),
                min_size=min_size,
                max_size=max_size,
                command_timeout=30,
                init=_init_connection,
            )
            _pools[domain] = (loop, pool)
    return _pools[domain][1]


async def close_all() -> None:
    """Close all connection pools (call on shutdown)."""
    for _loop, pool in _pools.values():
        await pool.close()
    _pools.clear()
