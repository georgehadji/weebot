# ADR 004: SQLite over PostgreSQL

**Status:** Accepted  
**Date:** 2026-06-01  
**Deciders:** Architecture Team  

## Context

weebot is a CLI-first agent framework that runs on developer machines.
It needs a persistence layer for sessions, events, skills, and trajectory
data. The choice is between SQLite (embedded, zero-config) and PostgreSQL
(client-server, more features).

## Decision

Use SQLite (via `aiosqlite` with connection pooling) as the primary
and only persistence backend.

## Rationale

- **Zero configuration** — No server to install, no connection strings to
  configure. The database is a single file (`weebot_sessions.db`).
- **Single-process architecture** — weebot runs as a single process on a
  developer machine. There is no need for concurrent writer access from
  multiple processes.
- **WAL mode** — SQLite's Write-Ahead Log provides concurrent reads
  during writes, which is sufficient for the read-heavy access pattern
  (many queries, few mutations per second).
- **Connection pooling** — `SQLiteConnectionPool` in `connection_pool.py`
  provides read/write connection management with proper async semantics.
- **Embedding** — SQLite can be bundled with the application; no external
  dependency management for production users.

## Consequences

- No horizontal scaling — SQLite is unsuitable for multi-process or
  multi-server deployments.
- Limited concurrency — fine for single-user agent sessions, but would
  need migration if we ever need a multi-tenant web service.
- Full-text search is limited — `LIKE` queries are used for session search
  instead of PostgreSQL `tsvector`.
- The `StateRepositoryPort` abstracts storage, so switching to PostgreSQL
  later would only require a new adapter, not application changes.
