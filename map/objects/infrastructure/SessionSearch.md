---
type: object
name: SessionSearch
code: SessionSearchPort, SqliteSessionSearch, plan_query, fts5_search
cluster: infrastructure
universe: live
status: stub
---

# SessionSearch

Search over what past sessions did: find the sessions that match a query, read the events around one hit, read one event.

## Why this shape
The `search_history` tool reached past ports into the FTS5 module and the connection pool, through two import exemptions. A port removes both. Two FTS tables answer one query because a stemmer cannot find the middle of a word and a trigram index cannot stem. ADR-024 has the reasoning.

## Shape
- `SessionSearchPort`: `discover(query, limit, syntax)`, `scroll(session_id, around_event_id, window)`, `read(event_id)`; `SessionSearchError` for a bad query (`weebot/application/ports/session_search_port.py`).
- `plan_query` splits a query: Latin words go to `event_fts` (porter + unicode61); any token of three characters or more, and every non-Latin token, goes to `event_fts_trigram`. `syntax="fts"` passes the query to the word index as written; `syntax="text"` quotes it. `SqliteSessionSearch` runs both, keeps each event's best score and groups by session (`weebot/infrastructure/persistence/session_search_sqlite.py`).
- Tables: `event_fts(session_id, event_id, ts UNINDEXED, event_type, summary, content)`, `event_fts_trigram` (same columns, no tool results, SQLite 3.34 or later) and `fts_watermark(session_id, last_event_idx)` (`weebot/infrastructure/persistence/fts5_search.py`). A table from before event ids is dropped and re-indexed on the next save of each session.

## Connected to
Written by `SQLiteStateRepository._index_saved_session` and cleared by `delete_session`. Read by the `search_history` tool, which gets `SqliteSessionSearch.at(DB_SESSIONS_PATH)` from `Container.tool_wiring` (`weebot/application/di/_factories.py`). Looks like but is not `StateRepositoryPort.search_sessions`, which returns events by word only.

## If you change this
**Hits:** `search_history` output and arguments, the index size on disk, the first save of every session after the schema changes, session deletion.
**Does not hit:** the `sessions` table, the in-memory `SessionMemoryIndex` on `Session`.

## Surfaces
The `search_history` tool (modes `discover`, `scroll`, `read`).

## See
`docs/adr/024-session-search-v2.md`
