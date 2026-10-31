---
type: object
name: Session
code: Session, SessionStatus, SessionContext, Fact, FactSource
cluster: domain
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# Session

The persisted record of one conversation or task: status, title, the full `AgentEvent` list and a typed `SessionContext` (facts, original prompt, skill, meta notes). A flow run reads and replaces it; `cli flow run` creates one.

## Why this shape
Event-sourced: the plan is not a field, it is the last `PlanEvent` in `events` with later `StepEvent`s applied (`weebot/domain/models/session.py:276-311`). Immutable like `Plan`: every mutator returns a new session through `model_copy` (`session.py:245-378`). `SessionContext` replaced a free `dict`; it keeps dict access (`get`, `[]`, `in`) and an `extra` bucket so old code and old rows still work (`session.py:52-62, 119-194`). A fact carries provenance (`Fact`, `session.py:37-49`) so an audited value can be told from an executor claim.

## Shape
- `SessionStatus` (`session.py:17-22`): `pending`, `running`, `waiting`, `completed`, `failed`.
- `Session` fields (`session.py:204-214`): `id` (validated `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, `session.py:216-228`), `user_id`, `agent_id`, `status`, `title`, `events: list[AgentEvent]`, `context`, `created_at`, `updated_at`, private `_memory_index: SessionMemory`.
- `_fix_broken_context` (`session.py:230-243`): a context saved as a repr string loads as empty.
- Events: `add_event` copies the index forward and indexes the new event (`session.py:245-255`); `replace_events` rebuilds the index (`session.py:257-271`, used by compaction). `add_user_message` appends the user's turn, keeping the UI's message id unless the session already holds it (`session.py:321-331`); `set_title` carries the index forward (`session.py:316-319`).
- Plan: `get_last_plan` asks `SessionMemory.find_last_plan` (`domain/services/session_memory.py:23-64`), else scans all events (`weebot/domain/models/session.py:280-311`). Both map StepEvent `started`/`running` to RUNNING, `completed`, `failed`; any other status is ignored.
- Facts: `set_fact(key, value, source=EXECUTOR, verified_by=None)` (`session.py:363-378`), `get_fact`, `get_fact_source`, `get_facts` (`session.py:385-403`). Max 100 facts; the oldest by insertion order are dropped (`session.py:88-97`), and `set_fact` pops and re-inserts the key so a rewritten key counts as newest (`session.py:371-374`). Pre-provenance bare values are wrapped as EXECUTOR on load (`session.py:99-117`).
- `SessionContext` fields (`session.py:64-84`): `skill_name`, `skill_content`, `skill_version`, `original_task` (alias `_original_task`), `last_prompt`, `facts`, `archived`, `archived_at`, `archive_ttl_days`, `trace_id`, `detected_language`, `meta_notes` (last 20, `session.py:353-361`), `extra`. `extra` also holds `TaskRunner`'s `retries_remaining` and `failure_reason`, so the retry budget and dead letter survive a restart (`application/services/task_runner.py:37-45`).

Consequences (read from source, not run):
- Dead: `is_completable`, `completion_summary`, `has_pending_approval`, `get_fact_source` have no caller in `weebot/` or `cli/` (grep 2026-10-24). `has_unresolved_wait_event` (`session.py:313-314`) is called only by `PlanActFlow._has_unresolved_wait_event` (`application/flows/plan_act_flow.py:505-507`), which nothing calls.
- Fact provenance is written but never used: no code passes `FactSource.AUDIT`, `FactSource.USER` or `verified_by`, and `get_fact_source` has no caller.
- `archived`, `archived_at`, `archive_ttl_days` and `detected_language` are never read or written outside this file; the language detector's docstring claims it stores into `detected_language` (`application/services/language_detector.py:7`).
- The 100-fact cap drops by insertion order. Per-step keys accumulate (`correction_original:<step>`, `reviewing.py:131, 180`; `constraint_gate_ack:<step>`, `weebot/application/flows/states/_execution_gates.py:130, 147`). A gate flag rewritten late, such as `atomic_mail_inbound_pending` (set at `weebot/application/flows/states/_step_run.py:110`, read at `weebot/application/flows/states/_execution_gates.py:98`), moves to newest on each write and is not the first evicted (F68, `tests/unit/fixes/test_fact_cap_keeps_fresh_flags.py`); a key written once early and never rewritten can still be evicted in a long session, and `get_fact` then returns `None`.
- Resume rebuilds the plan from the last `PlanEvent` plus later `StepEvent`s. The executor yields `COMPLETED` (`application/agents/executor/_base.py:647`); when the evidence audit then re-queues the step or marks it UNVERIFIED, `evidence_gate` emits a new `PlanEvent` with the changed plan (`application/flows/states/evidence_gate.py:15-62`, called from `weebot/application/flows/states/executing.py:157-162, 277`), so a resumed `get_last_plan` sees the downgrade (F69, `tests/unit/fixes/test_audit_downgrade_is_persisted.py`).
- `SessionMemory` keeps at most 100 indices per event type (`session_memory.py:14-17`); with more than 100 `step` events after the last plan, the oldest are not reconciled. `copy()` always rebuilds with the default 100 (`session_memory.py:74`).
- The comments at `session.py:249-252` and `session_memory.py:69-70` say `model_copy()` drops private attributes. With pydantic in `.venv` (checked 2026-10-24) `set_status()` returns a session that shares the same `_memory_index` object. Harmless today, because only `add_event` and `replace_events` mutate the index and both copy it first.
- A session built from a DB row has an empty index (`infrastructure/persistence/sqlite_state_repo.py:563-575`), so `get_last_plan` falls back to the full scan until a new `PlanEvent` is added.
- The StepEvent-to-status map is written twice (`session.py:301-306`, `session_memory.py:54-59`).

## Connected to
- **Owns** `events` (Event card) and `SessionContext`/`Fact`. **Indexes with** `SessionMemory` (`weebot/domain/services/session_memory.py:11`).
- **Persisted by** `StateRepositoryPort` / `SQLiteStateRepository` (`_row_to_session`, `sqlite_state_repo.py:540-575`); see that card.
- **Read and replaced by** `PlanActFlow` (`plan_act_flow.py:256, 380`), `FlowRouter` (`flow_router.py:75-100, 171-194`), the flow states, `TaskRunner` (`application/services/task_runner.py:339, 368-370, 384-395`; when the flow persists its own session, the runner writes once at the end from the flow's copy, audit A25), CQRS handlers (`execute_step_handler.py:77-83`, `update_plan_handler.py:40-74`, `plan_queries.py:30`, `create_plan_handler.py:44-122`; `active_queries.py` lists sessions and reads counts from `session_activity` without loading events), `MemoryCompactor` (`memory_compactor.py:79`), `MetaAnalysisState` (`meta_analysis.py:82`).
- **Looks like but is not:** `GatewaySession` (`domain/models/gateway_session.py:101`), a chat-gateway mapping; legacy `Project` (`domain/legacy_models.py:125`); a flow (`PlanActFlow`).

## If you change this
**Hits:** session persistence and every stored row (field names are JSON keys), resume (`get_last_plan`), the gate flags in facts (inbound mail, constraint ack, `plan_pending_approval` and the retry budget in `extra`), compaction, web session responses. Tests: `tests/unit/test_session_replace_events.py`, `tests/unit/test_session_queries.py`, `tests/unit/interfaces/web/test_session_response.py`, `tests/unit/test_executing_inbound_mail_gate.py`, `tests/unit/test_constraint_gate_phase5.py`, `tests/unit/application/flows/test_user_gate_answer_is_honoured.py`, `tests/unit/application/flows/test_a_state_gets_the_value_it_asks_for.py`, `tests/unit/fixes/test_premortem_plan_persisted.py`, `tests/unit/fixes/test_f36_dppm_plan_persisted.py`, `tests/unit/test_plan_template_cache_is_gated.py`, `tests/unit/test_sre_bug_fixes.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/integration/test_postgresql_adapter.py`.
**Does not hit:** the event store audit journal (separate table, EventStore card); gateway sessions.

## Surfaces
`python -m cli.main flow list|resume|cancel`; web session endpoints and the session rail (`SessionPresenceEvent`).

## See
`weebot/domain/models/session.py`
