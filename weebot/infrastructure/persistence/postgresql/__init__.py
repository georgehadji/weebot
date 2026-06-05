"""PostgreSQL persistence adapters for weebot.

Requires ``asyncpg`` and a running PostgreSQL instance.  Switch with
``WEEBOT_DB_BACKEND=postgresql`` environment variable — SQLite is the default.

Per-domain connection pools:
  - ``weebot_sessions`` → session state, events
  - ``weebot_skills``   → skills, trajectories, knowledge graph
  - ``weebot_cache``    → response cache, tool data
"""
from __future__ import annotations

POSTGRESQL_AVAILABLE = False
try:
    import asyncpg  # noqa: F401
    POSTGRESQL_AVAILABLE = True
except ImportError:
    pass
