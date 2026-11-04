# ADR-024: Session search finds substrings and non-Latin text, through a port

**Date:** 2026-11-04
**Status:** Implemented 2026-11-04 (plan H15, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Proceed". The Postgres part is not built (see Consequences).
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`search_history` searched `event_fts`, a `porter unicode61` table, and had these faults:

- A fragment of a word found nothing ("onfig" does not find "config"), and a stemmer cannot read Greek or CJK text.
- `_sanitize_fts_query` quoted every token, so the operators the tool text advertised (`OR`, `NOT`, prefix `*`) never worked.
- The rows carried no event id or timestamp, so a hit could not be located in its session.
- The indexing watermark lived in memory. After each restart a session was cleared and indexed again.
- The tool imported `fts5_search` and `connection_pool` from the infrastructure layer, through two entries in `.importlinter`.

## Decision

1. **Two tables.** `event_fts` is rebuilt with `event_id` and `ts` (both unindexed). `event_fts_trigram` has the same columns and the `trigram` tokenizer (SQLite 3.34 or later; the build is probed, and without it the table is not made and a warning is logged). Tool-result rows stay out of the trigram table, for size.
2. **Derived data, no data migration.** A pre-H15 `event_fts` is dropped with the watermarks. Each session is indexed again on its next save.
3. **A stored watermark.** `fts_watermark(session_id, last_event_idx)` is written in the same transaction as the rows it counts. The repository keeps its dict as a cache. A restart indexes only new events; a session whose row now holds fewer events than the watermark is still cleared and indexed again.
4. **`SessionSearchPort`** (`discover`, `scroll`, `read`), implemented by `SqliteSessionSearch`. `discover` returns one row per session, with its best event, its score and its number of matching events.
5. **The query planner is pure.** With `syntax="text"` a Latin token goes to the word index, and any token of three characters or more also goes to the trigram index; a non-Latin token goes to the trigram index only. The results are merged. With `syntax="fts"` the query reaches the word index as written, and a malformed one is a `SessionSearchError`.
6. **The tool** takes the port through its constructor and gains `mode` (`discover`, `scroll`, `read`) and `syntax`. Both import exemptions are deleted; `import_exemptions` goes from 58 to 56.

## Consequences

- A fragment of three or more characters finds the word, and Greek and CJK queries find text. A one- or two-character CJK word finds nothing: the trigram tokenizer cannot match fewer than three characters. There is no `LIKE` fallback.
- `syntax="fts"` is checked by running it. The error text is SQLite's.
- The first save of every session after the upgrade writes the whole session again, and the trigram table adds disk use for every event that is not a tool result. Not measured.
- A bm25 score on a small corpus is near zero. The tool reports it as a rank hint, not a probability.
- `discover` ranks sessions by their best event. It does not weigh several matching events beyond the `hits` count.
- **Not built:** the Postgres `pg_trgm` GIN index (an alembic revision). The tool still searches the SQLite file at `DB_SESSIONS_PATH`, as before, whatever backs `StateRepositoryPort`.
- `StateRepositoryPort.search_sessions` still returns events by word only, as before.
