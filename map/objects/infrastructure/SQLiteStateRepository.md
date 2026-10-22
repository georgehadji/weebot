---
type: object
name: SQLiteStateRepository
code: SQLiteStateRepository
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# SQLiteStateRepository

The default `StateRepositoryPort` adapter: stores sessions and a set of side tables (behavioral rules, corrections, commitments, plan templates, memory metadata, session constraints, opportunities) in one SQLite file. A facade: it owns the pool and schema and delegates per-topic queries to small helper repos.

## Why this shape
The port declares only 7 methods (`save_session`, `load_session`, `list_sessions`, `update_session_status`, `delete_session`, `search_sessions`, `get_low_salience_entries`; `application/ports/state_repo_port.py:10-58`), but the class has about 36 async methods. The other ~29 (behavioral rules, corrections, constraints, opportunities, memory metadata, plan templates, commitments) exist only here, so most of the code is one-line delegation to `SessionQueries`, `MemoryMetadataRepo`, `CommitmentRepo`, `BehavioralRuleRepo` (with `OpportunityRepo`, `PlanTemplateRepo`), `CorrectionRecordRepo`, `SessionConstraintRepo` (`weebot/infrastructure/persistence/sqlite_state_repo.py:44-74, 87-99`). Everything is lazy: the pool, the schema and the helpers are created on first use (`:78-99`).

## Shape
- File: `./weebot_sessions.db` by default (`:55`); the actual path comes from `DatabaseRouterPort.get_db_path("sessions")` (`:80`). Pool: `get_or_create_pool(path, max_read_connections=5, enable_wal=True)` (`:81`). `_ensure_schema` creates tables `sessions`, `pending_opportunities`, `behavioral_rules`, `memory_metadata`, `plan_templates`, `commitments`, `correction_records`, `session_constraints`, plus the FTS5 table via `ensure_fts5_table` (`:114-244`).
- A session is **one row**: `events_json` holds every event as JSON and `context_json` the context (`:118-129`). `SessionQueries.save` trims the oldest events until `events_json` fits `MAX_EVENTS_JSON_BYTES` (`_session_queries.py:28-47`); the ceiling lives only there.
- `save_session` (`:248`) does three separate write transactions in this order: the session row, then commitments extracted from assistant messages (failure is logged, session still saved, `:293-316`), then FTS5 indexing of events (`:318-384`).
- FTS5 index: `_fts5_indexed` is a **per-instance, in-memory** watermark of how many events of each session were indexed (`:62-65`). A fresh repository starts from zero and, for a session it has not seen, clears that session's index rows and re-indexes everything (replace, not append, `:339-359`). The watermark advances only as far as indexing succeeded (`:381-384`).
- `list_sessions(load_events=False)` by default: list views skip event deserialization (`:393-416`). Callers that read `.events` must pass `load_events=True`.
- `delete_session` deletes the row and then best-effort clears FTS5 rows (`:422-431`); `search_sessions` truncates the query to 500 chars (`:438`).
- Event rows are rebuilt through a Pydantic `TypeAdapter(AgentEvent)` (`:444-453`).

## Who calls what
Found by grepping for calls on receivers named `*repo*`, `state_manager` or `_state` (2026-10-21), so a caller that holds the repo under another name would be missed. Paths are under `weebot/` unless noted.

**Port methods**
| Method | Callers |
|---|---|
| `save_session` | flows: `chat_flow.py`, `collaborators/{event_emitter,flow_persistence,user_pause}.py`, `event_publisher.py`, `states/{chat_message,completed,plan_review}.py`; CQRS: `handlers/{create_plan,update_plan,summarize}_handler.py`, `behaviors/save_policy.py`; `services/task_runner.py`; `use_cases/dispatch_session_input.py`; web: `routers/{chat_router,sessions}.py`; CLI: `interfaces/cli/agent_runner.py`, `cli/commands/dream.py`; `scheduling/default_jobs.py` |
| `load_session` | CQRS handlers (create_plan, execute_step, update_plan, summarize, process_message, plan_queries, trajectory) and `save_policy.py`; `flows/collaborators/fact_resolver.py`; services (`session_search_service`, `task_runner`, `trajectory_exporter`); web: `interfaces/web/main.py`, `routers/{chat_router,ops_router,sessions,webhook}.py`; gateway: `interfaces/gateways/telegram.py`; CLI: `cli/main.py`, `cli/commands/flow.py`, `interfaces/cli/agent_runner.py`; `scheduling/default_jobs.py` |
| `list_sessions` | web: `routers/{chat_router,dashboard,health,sessions}.py`; MCP: `mcp/resources.py`; CLI: `cli/main.py`, `cli/commands/hyper.py`, `interfaces/cli/agent_runner.py`; `cqrs/handlers/active_queries.py`; `services/{task_runner,trajectory_exporter}.py`; monitors/health: `infrastructure/monitors/session_staleness_monitor.py`, `infrastructure/observability/health_checks.py`; `scheduling/default_jobs.py` |
| `update_session_status` | `services/task_runner.py` only |
| `delete_session` | `services/session_deletion_orchestrator.py` only |
| `search_sessions` | `services/session_search_service.py` only |
| `get_low_salience_entries` | `services/memory_lifecycle_service.py`, `services/user_model_consolidator.py` |

**Extra methods (not on the port; reached by duck typing)**
| Methods | Callers |
|---|---|
| `count_sessions` | `interfaces/web/routers/sessions.py` |
| `save_behavioral_rule`, `list_behavioral_rules` | `services/behavioral_learner.py` (+ `user_model_consolidator.py` for list) |
| `save_correction_record`, `count_corrections_by_category`, `get_correction_patterns` | `services/correction_tracker.py` |
| `save/revoke/list_active_session_constraint(s)` | `flows/collaborators/session_constraint_accumulator.py` |
| `save_opportunity` | `services/opportunity_engine.py`; `list_opportunities`, `mark_opportunity_presented`, `accept_opportunity` have no caller in `weebot/` or `cli/` |
| `upsert_memory_metadata`, `delete_memory_entries` | `services/{user_model_consolidator,memory_lifecycle_service}.py`, `tools/persistent_memory.py` |
| `get_memory_entry` | `agents/executor/_base.py` (user-profile lookup, inside `try/except Exception`), `agents/executor/_prompt_builder.py` |
| `save_plan_template` / `increment_template_use` | `flows/states/completed.py` / `cqrs/handlers/create_plan_handler.py` |
| `find_plan_templates_by_hash`, `list_all_plan_templates` | `domain/services/plan_template_cache.py` (domain layer) |
| `list_commitments`, `get_pending_commitments`, `update_commitment_status` | `domain/services/commitment_engine.py` (domain layer); `save_commitment` is called only inside this class |

Consequence: `InMemoryStateRepo` and the PostgreSQL repo implement the port but only `sqlite_state_repo.py` defines these extra methods (grep of `def get_memory_entry`, `upsert_memory_metadata`, `save_commitment`, `increment_template_use`). Code that calls them on another implementation would raise `AttributeError`; the executor's profile lookup would hide it in its `except`.

## Connected to
- **Implements** `StateRepositoryPort` (`application/ports/state_repo_port.py`); 66 files under `weebot/` mention the port. Other implementers: `persistence/in_memory_state_repo.py`, `persistence/postgresql/state_repo.py`.
- **Constructed by** `FactoriesMixin._create_state_repo` (`application/di/_factories.py:43`) and directly at `infrastructure/observability/health_checks.py:307` and `tools/persistent_memory.py:166`. `cli/main.py:72` tells callers not to construct it directly.
- **Pool:** `persistence/connection_pool.py` (`SQLiteConnectionPool`, shared with the event store through `get_or_create_pool`).
- **Looks like but is not:** the other port implementers above; the **event store** (a separate DB file and table, see its card); PostgreSQL adapters under `persistence/postgresql/` (scaffolded, not covered).

## If you change this
**Hits:** every flow state that saves or loads a session; session deletion and search; the FTS5 index contents; any code that reads `session.events` after `list_sessions`; `Session`/`SessionContext` serialization (`events_json`, `context_json` shape); tests that construct it: `tests/e2e/test_persistence.py`, `tests/e2e/test_flow_e2e.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/integration/test_state_manager.py` and 14 more (18 files mention the class).
**Does not hit:** the event store DB; LLM adapters; FlowRouter (it reads the `Session` object, not SQL).

## Surfaces
CLI (`flow`, `dream`, `hyper`, agent runner), web routers, the Telegram gateway, the MCP resources, scheduled jobs and every flow state that saves a session. See "Who calls what".

## See
`weebot/infrastructure/persistence/sqlite_state_repo.py`
