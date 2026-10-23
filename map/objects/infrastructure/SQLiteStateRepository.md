---
type: object
name: SQLiteStateRepository
code: SQLiteStateRepository
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# SQLiteStateRepository

The default `StateRepositoryPort` adapter: stores sessions and a set of side tables (behavioral rules, corrections, commitments, plan templates, memory metadata, session constraints, opportunities) in one SQLite file. A facade: it owns the pool and schema and delegates per-topic queries to small helper repos.

## Why this shape
The port declares 8 methods (`save_session`, `load_session`, `list_sessions`, `count_sessions`, `update_session_status`, `delete_session`, `search_sessions`, `get_low_salience_entries`; `application/ports/state_repo_port.py:10-72`). The class also implements the role Protocols of `state_roles_port.py` and `weebot/domain/ports.py` (behavioral rules, corrections, session constraints, opportunities, memory metadata, plan-template writes and reads, commitments; `weebot/infrastructure/persistence/sqlite_state_repo.py:60-70`, `application/ports/state_roles_port.py:1-13`). Those methods are one-line delegation to `SessionQueries`, `MemoryMetadataRepo`, `CommitmentRepo`, `BehavioralRuleRepo`, `OpportunityRepo`, `PlanTemplateRepo`, `CorrectionRecordRepo`, `SessionConstraintRepo` (`sqlite_state_repo.py:38-49, 92-100`). Everything is lazy: the pool, the schema and the helpers are created on first use (`:104-125`).

## Shape
- File: `DB_SESSIONS_PATH` by default (`:81`), which is `WEEBOT_SESSIONS_DB` or `./weebot_sessions.db` (`weebot/config/settings.py:19`); the actual path comes from `DatabaseRouterPort.get_db_path("sessions")` (`sqlite_state_repo.py:106`). Pool: `get_or_create_pool(path, max_read_connections=5, enable_wal=True)` (`:107`). `_ensure_schema` creates tables `sessions`, `pending_opportunities`, `behavioral_rules`, `memory_metadata`, `plan_templates`, `commitments`, `correction_records`, `session_constraints`, plus the FTS5 table via `ensure_fts5_table` (`:140-270`).
- A session is **one row**: `events_json` holds every event as JSON and `context_json` the context (`:144-154`). `SessionQueries.save` drops the oldest events until `events_json` fits `MAX_EVENTS_JSON_BYTES` (10 MB, `weebot/config/constants.py:35`), never the last `plan` event, and logs one warning (`_session_queries.py:39-75`); the ceiling lives only there.
- `save_session` (`sqlite_state_repo.py:274`) does three separate write transactions in this order: the session row (`:301`), then commitments extracted from assistant messages (failure is logged, session still saved, `:319-342`), then FTS5 indexing of events (`:344-410`).
- FTS5 index: `_fts5_indexed` is a **per-instance, in-memory** watermark of how many events of each session were indexed (`:88-89`). A fresh repository starts from zero and, for a session it has not seen, clears that session's index rows and re-indexes everything (replace, not append, `:365-385`). The watermark advances only as far as indexing succeeded (`:407-410`).
- `list_sessions(load_events=False)` by default: list views skip event deserialization (`:419-442`). Callers that read `.events` must pass `load_events=True`.
- `delete_session` deletes the row and then best-effort clears FTS5 rows (`:448-457`); `search_sessions` truncates the query to 500 chars (`:464`).
- Event rows are rebuilt through a Pydantic `TypeAdapter(AgentEvent)`, falling back to `MessageEvent` (`:473-502`).

## Who calls what
Found by grepping for `.method(` calls in `weebot/` and `cli/` and dropping receivers that are not a state repository (2026-10-24), so a caller that reaches the repo another way would be missed. Paths are under `weebot/` unless noted.

**Port methods**
| Method | Callers |
|---|---|
| `save_session` | flows: `chat_flow.py`, `plan_act_flow.py`, `collaborators/user_pause.py`, `event_publisher.py`, `states/{chat_message,completed,plan_review}.py`; CQRS: `handlers/{create_plan,update_plan,summarize}_handler.py`, `behaviors/save_policy.py`; `services/task_runner.py`; `use_cases/dispatch_session_input.py`; persistence wrappers: `infrastructure/persistence/{legacy_project_adapter,session_persistence_adapter}.py`; web: `routers/{chat_router,sessions}.py`; CLI: `interfaces/cli/agent_runner.py`, `cli/commands/dream.py`; `scheduling/default_jobs.py` |
| `load_session` | CQRS handlers (create_plan, execute_step, update_plan, summarize, process_message, plan_queries, trajectory) and `save_policy.py`; `flows/collaborators/fact_resolver.py`; services (`session_search_service`, `task_runner`, `trajectory_exporter`); `infrastructure/persistence/legacy_project_adapter.py`; web: `interfaces/web/main.py`, `routers/{chat_router,ops_router,sessions,sse,webhook}.py`; gateway: `interfaces/gateways/telegram.py`; CLI: `cli/main.py`, `cli/commands/flow.py`, `interfaces/cli/agent_runner.py`; `scheduling/default_jobs.py` |
| `list_sessions` | web: `routers/{chat_router,dashboard,health,sessions}.py`; MCP: `mcp/resources.py`; CLI: `cli/main.py`, `cli/commands/hyper.py`, `interfaces/cli/agent_runner.py`; `cqrs/handlers/active_queries.py`; `services/{task_runner,trajectory_exporter}.py`; `infrastructure/persistence/legacy_project_adapter.py`; monitors/health: `infrastructure/monitors/session_staleness_monitor.py`, `infrastructure/observability/health_checks.py`; `scheduling/default_jobs.py` |
| `count_sessions` | `interfaces/web/routers/sessions.py` |
| `update_session_status` | `services/task_runner.py`; `cli/commands/flow.py:253` |
| `delete_session` | `services/session_deletion_orchestrator.py` only |
| `search_sessions` | `services/session_search_service.py` only |
| `get_low_salience_entries` | `services/memory_lifecycle_service.py`, `services/user_model_consolidator.py` |

**Role methods (not on the port; callers narrow with `as_role`)**
| Methods | Callers |
|---|---|
| `save_behavioral_rule`, `list_behavioral_rules` | `services/behavioral_learner.py` (+ `user_model_consolidator.py` for list) |
| `save_correction_record`, `count_corrections_by_category`, `get_correction_patterns` | `services/correction_tracker.py` |
| `save/revoke/list_active_session_constraint(s)` | `flows/collaborators/session_constraint_accumulator.py` |
| `save_opportunity` | `services/opportunity_engine.py` |
| `upsert_memory_metadata`, `delete_memory_entries` | `services/{user_model_consolidator,memory_lifecycle_service}.py`, `tools/persistent_memory.py` |
| `get_memory_entry` | `agents/executor/_base.py` (user-profile lookup), `agents/executor/_prompt_builder.py` |
| `save_plan_template` / `increment_template_use` | `flows/states/completed.py` / `cqrs/handlers/create_plan_handler.py` |
| `find_plan_templates_by_hash`, `list_all_plan_templates` | `domain/services/plan_template_cache.py` (domain layer) |
| `list_commitments`, `update_commitment_status` | `domain/services/commitment_engine.py` (domain layer); `save_commitment` is called only inside this class (`sqlite_state_repo.py:334`) |

Consequence: `InMemoryStateRepo` and the PostgreSQL repo implement the port but none of the roles (only `sqlite_state_repo.py` defines `save_behavioral_rule`, `get_memory_entry`, `save_commitment`, `save_plan_template`; grep 2026-10-24). Callers resolve a role with `as_role` (`weebot/domain/ports.py:87-100`), get `None` on those repositories, and skip the feature instead of raising `AttributeError` (W5.1, F26), for example `application/agents/executor/_base.py:568-571`.

## Connected to
- **Implements** `StateRepositoryPort` (`application/ports/state_repo_port.py`); 68 files under `weebot/` mention the port (grep 2026-10-24). Other implementers: `persistence/in_memory_state_repo.py`, `persistence/postgresql/state_repo.py`.
- **Constructed by** `FactoriesMixin._create_state_repo` (`application/di/_factories.py:34-43`; PostgreSQL instead when `WEEBOT_DB_BACKEND=postgresql`, `:35-40`) and directly at `infrastructure/observability/health_checks.py:294` and `tools/persistent_memory.py:161`. `cli/main.py:71-72` tells callers not to construct it directly.
- **Pool:** `persistence/connection_pool.py` (`SQLiteConnectionPool`, shared with the event store through `get_or_create_pool`).
- **Looks like but is not:** the other port implementers above; the **event store** (a separate DB file and table, see its card); PostgreSQL adapters under `persistence/postgresql/` (scaffolded, not covered).

## If you change this
**Hits:** every flow state that saves or loads a session; session deletion and search; the FTS5 index contents; any code that reads `session.events` after `list_sessions`; `Session`/`SessionContext` serialization (`events_json`, `context_json` shape); tests that construct it: `tests/e2e/test_persistence.py`, `tests/e2e/test_flow_e2e.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/integration/test_state_manager.py` and 14 more (18 files mention the class).
**Does not hit:** the event store DB; LLM adapters; FlowRouter (it reads the `Session` object, not SQL).

## Surfaces
CLI (`flow`, `dream`, `hyper`, agent runner), web routers, the Telegram gateway, the MCP resources, scheduled jobs and every flow state that saves a session. See "Who calls what".

## See
`weebot/infrastructure/persistence/sqlite_state_repo.py`
