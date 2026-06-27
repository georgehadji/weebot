# ADR-003: SQLite as Primary Store (with PostgreSQL Migration Path)

**Status:** Accepted
**Date:** 2025-07-17
**Deciders:** Architecture team

## Context

Weebot needs persistent storage for sessions, events, trajectories, user
profiles, skill definitions, knowledge graphs, and cron job schedules.
In early development, the priority was rapid iteration and zero-infrastructure
setup for individual developers. Production scaling was a deferred concern.

Requirements: single-developer workflow must work with `pip install` and
no external services. Multi-process scaling must be achievable without a
full data migration.

## Decision

Use **SQLite via aiosqlite** as the primary store, with Alembic for
schema migrations and a clear migration path to PostgreSQL.

- **Session state** → SQLite (`weebot_sessions.db`) via
  `SQLiteStateRepository`. Single file, zero config.
- **Migrations** → Alembic scripts in `alembic/versions/`. `alembic upgrade
  head` at startup.
- **Connection pool** → `aiosqlite` single-connection with WAL mode for
  concurrent readers.
- **Scheduler jobs** → Separate SQLite file (`scheduler_jobs.db`) to avoid
  lock contention with session writes.

### PostgreSQL Migration Path

When multi-process scaling is required:
1. Extract `StateRepositoryPort` — already exists.
2. Implement `PostgresStateRepository(StateRepositoryPort)` using `asyncpg`.
3. Add `connection_pool_port` abstraction for managing write/read replicas.
4. Swap DI binding: `container.bind(StateRepositoryPort, PostgresStateRepository)`.
5. No agent loop or flow code changes needed — port abstraction handles it.

## Consequences

**Positive:**
- Zero-infrastructure setup: `pip install` + `python run_mcp.py` works.
- Fast iteration: `rm weebot_sessions.db` resets everything.
- Alembic autogenerate detects schema drift.

**Negative:**
- Single-writer bottleneck. Under 10+ concurrent agents, write contention
  on `weebot_sessions.db` will spike.
- No read replicas. Every query hits the same file.
- Schema migrations are more manual than with a managed Postgres service.
- Scheduler has its own SQLite file (a known workaround, not a clean
  multi-database design).

**Compliance:** All persistence code depends on `StateRepositoryPort` or
other abstract ports, never on `sqlite3` directly. The `tools-no-db`
import-linter contract enforces this for the tool layer.
