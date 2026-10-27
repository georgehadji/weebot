---
type: object
name: Event store (audit journal)
code: AsyncEventStore (alias EventStore)
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-27
commit: f36ab8e5
---

# Event store

An append-only SQLite journal of events and per-session cost, used for audit, cost reporting and debugging. It is **not** where a session's own event list lives: that is the `events_json` column in the state repository.

## Why this shape
Kept apart from session state so event logging is a cheap insert and can fail without affecting a run: `DurableEventBus` journals every event best-effort before fan-out and "never blocks event delivery" (`weebot/infrastructure/event_bus.py:180-199`, journal helpers `:221-262`). Behind `EventStorePort` so tests can use an in-memory store (`application/ports/event_store_port.py:1-8`).

## Shape
- Class `AsyncEventStore` (`weebot/infrastructure/event_store.py:94`), exported under the old name `EventStore = AsyncEventStore` (`:487-488`); DI imports `EventStore` (`application/di/_factories.py:99-102`).
- File: `~/.weebot/events.db` by default (`:106`), created on construction (`:107`). Pool: shared `SQLiteConnectionPool`, 3 read connections, WAL (`:111-119`).
- Tables: `sessions(id, started_at, ended_at, status, user_id, total_cost, total_tokens)` and `events(id, timestamp, session_id, event_type, data_json, cost, model, tokens_used)` with indexes on session, type, timestamp (`:121-158`). Note this `sessions` table is not the state repository's `sessions` table.
- Cost columns are written for one event type only: `DurableEventBus._journal_domain` passes `cost`, `model` and `tokens_used` when the event is `LLMCallCompleted` (W4.1, 2026-10-22), which `CascadeExecutor` raises after each successful executor LLM call. Every other event keeps the defaults (0, "", 0). LLM calls outside the executor cascade (planner, verifier) are not recorded.
- `log_event` (`:161`) in one write transaction: inserts a session row if missing, inserts the event, adds `cost` and `tokens_used` to the session totals; returns the new event id (`:176-195`).
- `get_cost_window(window_hours)` sums the `llm_call_completed` rows by model: the one cost query (W4.2).
- Also: `get_session_events`, `get_cost_summary`, `query_recent_events` (used by DreamerAgent per the port docstring), `start_session`/`end_session`, `export_session`, `delete_session`, `cleanup_old_sessions(days=30)`, `get_stats` (`:197-449`).
- `delete_session` exists so a deleted session's journal does not survive: the port docstring says `DurableEventBus` journals every agent event here (`event_store_port.py`, `delete_session` doc).

## Connected to
- **Registered as** `EventStorePort` in `configure_defaults` (`application/di/__init__.py:161`) and injected into `DurableEventBus` by `_create_event_bus`, with `AsyncEventBus` as the inner bus. A set `WEEBOT_VALKEY_URL` or `WEEBOT_REDIS_URL` makes it raise at start-up (W4.3, F24).
- **Writers:** `DurableEventBus` (every agent and domain event, `event_bus.py:227-262`) is the only live writer found. The unused `EventLogger` (formerly infrastructure/event_logging.py) was deleted in W4.2. Do not confuse it with `interfaces/cli/event_logger.py`, which subscribes to the bus and prints.
- **Readers:** `get_cost_window` backs `GetCostSummaryHandler`, which CLI `costs`, MCP `weebot://costs` and the ops API (`/api/costs/summary`, since W7.1) use. `get_cost_summary(session_id)` is used by `export_session`. Other methods are reached via `EventStorePort` by `completed.py`, `trajectory_handler.py`, `interfaces/web/dependencies.py`, `ports/dreamer_port.py` (mentions; per-method use not traced).
- **Session deletion:** `tests/unit/interfaces/web/test_session_deletion_wiring.py` covers the purge wiring.
- **Looks like but is not:** `AsyncEventBus` / `DurableEventBus` (live fan-out to subscribers); the state repository's `events_json`; `weebot/infrastructure/events/` (broker and Valkey/Redis bus code).

## If you change this
**Hits:** `DurableEventBus` (every event passes through `log_event`), session-deletion orchestration, the DreamerAgent failure-signal query. Not cost reporting: no live cost view reads this store (see Surfaces).
**Does not hit:** the state repository and its FTS5 index; LLM adapters; flow control (journal failures are swallowed). Only one test file mentions `event_store` by name; the class itself has no direct unit test found in `tests/`.

## Surfaces
Audit data only. Cost views do **not** read this store:
- Fixed in W4.2 (F23): `GetCostSummaryHandler` no longer reads a fresh container's empty `cascade_tracker`. It asks the event store for the spend in `window_hours` (`application/cqrs/handlers/active_queries.py:71-92`, `infrastructure/event_store.py:271`), which `DurableEventBus` fills from `LLMCallCompleted`, and fails when no event store is configured. The CLI `costs` command, MCP `weebot://costs` and the ops API share it. It is also affected by the `mediator.send` defect on the Mediator card.
- `python -m cli.main costs` prints hard-coded rows ("Today $2.45 / 12,340"; comment "Placeholder data", `cli/main.py:255-268`).
- MCP `build_costs_json` reads a tracker only if one is passed to `WeebotMCPServer`; `run_mcp.py:59-63` does not pass one, so it returns its "Pass cascade_tracker=" note (`mcp/resources.py:221-231`).
- `AsyncEventStore.get_cost_summary` computes real totals from this DB but nothing calls it.

## See
`weebot/infrastructure/event_store.py`
