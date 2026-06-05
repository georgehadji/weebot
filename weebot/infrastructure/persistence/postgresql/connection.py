"""PostgreSQL connection pool management — per-domain pools.

Each domain gets its own connection pool so a schema migration for one
domain never locks the others.  All pools use the same PostgreSQL server
but different database names (or schemas).
"""
from __future__ import annotations

import os
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_DSN = os.environ.get(
    "WEEBOT_PG_DSN",
    "postgresql://weebot:weebot@localhost:5432/weebot_sessions",
)

# Per-domain database names (appended to base DSN)
_DOMAIN_DATABASES = {
    "sessions": "weebot_sessions",
    "skills": "weebot_skills",
    "cache": "weebot_cache",
}

# Global pool cache
_pools: dict[str, Any] = {}


def _build_dsn(base_dsn: str, domain_db: str) -> str:
    """Replace the database name in *base_dsn* with *domain_db*."""
    import re
    # Replace last path segment (the database name)
    return re.sub(r"/([^/]+)$", f"/{domain_db}", base_dsn)


async def get_pool(domain: str = "sessions", min_size: int = 2, max_size: int = 10) -> Any:
    """Return an asyncpg connection pool for *domain*.

    Pools are cached globally so repeated calls return the same pool.
    """
    import asyncpg

    if domain not in _DOMAIN_DATABASES:
        raise ValueError(f"Unknown domain {domain!r}. Choose from {list(_DOMAIN_DATABASES)}")

    if domain in _pools:
        return _pools[domain]

    dsn = _build_dsn(_DEFAULT_DSN, _DOMAIN_DATABASES[domain])
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=30,
    )
    _pools[domain] = pool
    return pool


async def close_all() -> None:
    """Close all connection pools (call on shutdown)."""
    for domain, pool in _pools.items():
        await pool.close()
    _pools.clear()
