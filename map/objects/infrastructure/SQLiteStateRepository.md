---
type: object
name: SQLiteStateRepository
code: SQLiteStateRepository
cluster: infrastructure
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# SQLiteStateRepository

The default `StateRepositoryPort` adapter: stores sessions and a set of side tables (behavioral rules, corrections, commitments, plan and workflow templates, memory metadata, session constraints, opportunities) in one SQLite file. A facade: it owns the pool and schema and delegates per-topic queries to small helper repos.

## Why this shape
The port declares 11 methods (`save_session`, `save_session_if_unchanged`, `create_session`, `load_session`, `list_sessions`, `count_sessions`, `session_activity`, `update_session_status`, `delete_session`, `search_sessions`, `get_low_salience_entries`; `application/ports/state_repo_port.py:60-177`); four of them have load-then-save or paging defaults that this class overrides. `session_activity` answers list views with step, tool-call and message counts (`SessionActivity`, `application/ports/state_repo_port.py:16-57`) from two grouped queries over `events_json` (`_session_queries.py:205-235`, `sqlite_state_repo.py:516-520`), because `list_sessions` leaves events unloaded (audit R19). The class also implements the role Protocols of `state_roles_port.py` and `weebot/domain/ports.py` (behavioral rules, corrections, session constraints, opportunities, memory metadata, plan-template writes and reads, workflow templates, commitments; `weebot/infrastructure/persistence/sqlite_state_repo.py:67-78`, `application/ports/state_roles_port.py:1-12`). Those methods are one-line delegation to `SessionQueries`, `MemoryMetadataRepo`, `CommitmentRepo`, `BehavioralRuleRepo`, `OpportunityRepo`, `PlanTemplateRepo`, `WorkflowTemplateRepo`, `CorrectionRecordRepo`, `SessionConstraintRepo` (`sqlite_state_repo.py:40-56, 583-725`). Everything is lazy: the pool, the schema and the helpers are created on first use (`sqlite_state_repo.py:117-139`).

## Shape
- File: `DB_SESSIONS_PATH` by default (`sqlite_state_repo.py:89`), which is `WEEBOT_SESSIONS_DB` or `./weebot_sessions.db` (`weebot/config/settings.py:22`); the actual path comes from `DatabaseRouterPort.get_db_path("sessions")` (`sqlite_state_repo.py:119`). Pool: `get_or_create_pool(path, max_read_connections=5, enable_wal=True)` (`sqlite_state_repo.py:120`). `_ensure_schema` creates tables `sessions`, `pending_opportunities`, `behavioral_rules`, `memory_metadata`, `plan_templates`, `workflow_templates`, `commitments`, `correction_records`, `session_constraints`, plus the FTS5 table via `ensure_fts5_table` (`sqlite_state_repo.py:154-293`).
- A session is **one row**: `events_json` holds every event as JSON and `context_json` the context (`sqlite_state_repo.py:158-168`). `SessionQueries.save` drops the oldest events until `events_json` fits `MAX_EVENTS_JSON_BYTES` (10 MB, `weebot/config/constants.py:35`), never the last `plan` event, and logs one warning (`_session_queries.py:97-138`); the ceiling lives only there.
- `save_session` (`sqlite_state_repo.py:303`) does three separate write transactions in this order: the session row (`sqlite_state_repo.py:330`), then, in `_index_saved_session` (`sqlite_state_repo.py:344`), commitments extracted from assistant messages (failure is logged, session still saved, `sqlite_state_repo.py:363-390`; a per-instance `_commitments_scanned` watermark skips events already scanned, `sqlite_state_repo.py:367-382`), then FTS5 indexing of events (`sqlite_state_repo.py:392-458`).
- `save_session_if_unchanged` (`sqlite_state_repo.py:333-342`) is one guarded UPDATE on `updated_at` (`_session_queries.py:59-80`), runs the same `_index_saved_session` after a win, and returns False when the row moved; the compaction job uses it (`weebot/scheduling/default_jobs.py:95`). `create_session` (`sqlite_state_repo.py:297-301`) is load-then-save under a per-process lock, so a second replica could race it.
- FTS5 index: `_fts5_indexed` is a **per-instance, in-memory** watermark of how many events of each session were indexed (`sqlite_state_repo.py:96-97`). A fresh repository starts from zero and, for a session it has not seen, clears that session's index rows and re-indexes everything (replace, not append, `sqlite_state_repo.py:413-433`). The watermark advances only as far as indexing succeeded (`sqlite_state_repo.py:455-458`).
- `list_sessions(load_events=False)` by default: list views skip event deserialization (`sqlite_state_repo.py:467-490`). Callers that read `.events` must pass `load_events=True`.
- `delete_session` first deletes the session's `session_constraints` and `correction_records` rows (plan L1), then the session row, then best-effort clears FTS5 rows (`sqlite_state_repo.py:496-510`); `search_sessions` truncates the query to 500 chars (`sqlite_state_repo.py:522-523`).
- Event rows are rebuilt through a Pydantic `TypeAdapter(AgentEvent)`, falling back to `MessageEvent` (`sqlite_state_repo.py:531-538, 554-561`).

## Who calls what
Found by grepping for `.method(` calls in `weebot/` and `cli/` and dropping receivers that are not a state repository (2026-10-24), so a caller that reaches the repo another way would be missed. Paths are under `weebot/` unless noted.

**Port methods**
| Method | Callers |
|---|---|
| `save_session` | flows: `chat_flow.py`, `_run_prologue.py`, `collaborators/user_pause.py`, `event_publisher.py`, `states/{chat_message,completed,plan_review}.py`; CQRS: `handlers/{create_plan,update_plan,summarize}_handler.py`, `behaviors/save_policy.py`; `services/task_runner.py`; `use_cases/dispatch_session_input.py`; persistence wrappers: `infrastructure/persistence/session_persistence_adapter.py`; web: `routers/{chat_router,sessions}.py`; CLI: `interfaces/cli/agent_runner.py`, `cli/commands/{dream,flow}.py` |
| `load_session` | CQRS handlers (create_plan, execute_step, update_plan, summarize, process_message, plan_queries, trajectory) and `save_policy.py`; `flows/collaborators/fact_resolver.py`; services (`session_search_service`, `task_runner`, `trajectory_exporter`); web: `interfaces/web/main.py`, `routers/{chat_router,ops_router,sessions,sse,webhook}.py`; gateway: `interfaces/gateways/telegram.py`; CLI: `cli/main.py`, `cli/commands/flow.py`, `interfaces/cli/agent_runner.py`; `scheduling/default_jobs.py` |
| `list_sessions` | web: `routers/{chat_router,health,sessions}.py`; CLI: `cli/main.py`, `cli/commands/hyper.py`, `interfaces/cli/agent_runner.py`; `cqrs/handlers/active_queries.py`; `services/task_runner.py`; `infrastructure/observability/health_checks.py`. Paged through `all_sessions` (`state_repo_port.py:179-197`): `routers/dashboard.py`, `mcp/resources.py`, `services/trajectory_exporter.py`, `scheduling/default_jobs.py` |
| `count_sessions` | `interfaces/web/routers/{sessions,chat_router}.py` |
| `session_activity` | `cqrs/handlers/active_queries.py`, `interfaces/web/routers/chat_router.py` |
| `create_session` | `interfaces/web/routers/sessions.py` |
| `save_session_if_unchanged` | `scheduling/default_jobs.py` (compaction) |
| `update_session_status` | `services/task_runner.py`; `cli/commands/flow.py:313` |
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
| `get_memory_entry` | `agents/executor/_step_setup.py` (user-profile lookup), `agents/executor/_prompt_builder.py` |
| `save_plan_template` / `increment_template_use` | `flows/states/completed.py` / `cqrs/handlers/create_plan_handler.py` |
| `save_workflow_template`, `list_workflow_templates` | `services/workflow_memory.py` |
| `find_plan_templates_by_hash`, `list_all_plan_templates` | `domain/services/plan_template_cache.py` (domain layer) |
| `list_commitments`, `update_commitment_status` | `domain/services/commitment_engine.py` (domain layer); `save_commitment` is called only inside this class (`sqlite_state_repo.py:381`) |

Consequence: `InMemoryStateRepository` implements the port but none of the roles, while the PostgreSQL repo takes them from `PostgresRoleStores` (`persistence/postgresql/_role_stores.py:77`; grep 2026-10-30). Callers resolve a role with `as_role` (`weebot/domain/ports.py:87-99`), get `None` on a repository without it, and skip the feature instead of raising `AttributeError` (W5.1, F26), for example `weebot/application/agents/executor/_step_setup.py:128-131`.

## Connected to
- **Implements** `StateRepositoryPort` (`application/ports/state_repo_port.py`); 67 files under `weebot/` mention the port (grep 2026-10-30). Other implementers: `persistence/in_memory_state_repo.py`, `persistence/postgresql/state_repo.py`.
- **Constructed by** `FactoriesMixin._create_state_repo` (`application/di/_factories.py:41-50`; PostgreSQL instead when `WEEBOT_DB_BACKEND=postgresql`, `application/di/_factories.py:42-47`) and directly at `infrastructure/observability/health_checks.py:294` and `tools/persistent_memory.py:164`. `cli/main.py:71-72` tells callers not to construct it directly.
- **Pool:** `persistence/connection_pool.py` (`SQLiteConnectionPool`, shared with the event store through `get_or_create_pool`).
- **Looks like but is not:** the other port implementers above; the **event store** (a separate DB file and table, see its card); PostgreSQL adapters under `persistence/postgresql/` (scaffolded, not covered).

## If you change this
**Hits:** every flow state that saves or loads a session; session deletion and search; the FTS5 index contents; any code that reads `session.events` after `list_sessions`; `Session`/`SessionContext` serialization (`events_json`, `context_json` shape); tests that construct it: `tests/e2e/test_persistence.py`, `tests/e2e/test_flow_e2e.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/integration/test_state_manager.py`, `tests/unit/fixes/test_l1_delete_cascade.py` and 22 more (26 files mention the class).
**Does not hit:** the event store DB; LLM adapters; FlowRouter (it reads the `Session` object, not SQL).

## Surfaces
CLI (`flow`, `dream`, `hyper`, agent runner), web routers, the Telegram gateway, the MCP resources, scheduled jobs and every flow state that saves a session. See "Who calls what".

## See
`weebot/infrastructure/persistence/sqlite_state_repo.py`
