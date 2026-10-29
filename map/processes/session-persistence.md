---
type: process
name: session persistence
code: EventPublisher._persist_session, SessionPersistenceAdapter, SQLiteStateRepository, cancel_requests
cluster: application
universe: live
status: stale
verified: 2026-10-29
commit: e102c98e
consumes:
  - ../objects/application/PlanActFlow.md
  - ../objects/application/FlowRouter.md
  - ../objects/application/DIContainer.md
  - ../objects/domain/Session.md
  - ../objects/domain/Event.md
  - ../objects/domain/Plan.md
  - ../objects/interfaces/CLI.md
produces:
  - ../objects/infrastructure/SQLiteStateRepository.md
  - ../objects/domain/Session.md
---

# session persistence

**Input:** a `Session` mutated by the flow (one event added per `_emit`), or a session id to resume or cancel.
**Movement:** save: `EventPublisher` writes through `SessionPersistenceAdapter` (retry, dead-letter) or the bare state repo into one SQLite row; restore: the row is loaded, the plan rebuilt from the last `PlanEvent` plus later `StepEvent`s; cancel: a marker file the running process consumes.
**Output:** the `sessions` row (status, events JSON, context JSON); a resumed flow in `ExecutingState`; a cancelled flow.

## Steps
### Save
1. Every state emits through `PlanActFlow._emit`, which syncs the publisher's session and plan and takes the mutated session back (`weebot/application/flows/plan_act_flow.py:241-260`). The publisher is built once per flow with the flow's repo and `persistence_adapter` (`:214-229`, getter `:738-744`).
2. `EventPublisher.emit`: truth binding, credential sanitization, `session.add_event`, a checkpoint hook on `step` events, bus publish and domain events, then `_persist_session` when a state repo is set (`weebot/application/flows/event_publisher.py:63-93`). The save runs under `emit_lock` (`event_publisher.py:88-92`), so two concurrent emits persist in order and an older snapshot cannot overwrite a newer one. An emit that waited behind a save whose snapshot already held its event skips its own save (`_saved_seq`), so a slow write is retried once for the queue.
3. `_persist_session` uses the adapter when present and logs a dead-letter on `False`; without one it calls `state_repo.save_session` and logs a warning on failure (`event_publisher.py:172-183`).
4. The adapter comes from DI: `"session_persistence"` (`weebot/application/di/__init__.py:148`) builds `SessionPersistenceAdapter(repo=...)` with its default retry (`:625-633`); `build_flow` passes it to every `PlanActFlow` and `ChatFlow` (`weebot/application/flows/flow_builder.py:197, 197`).
5. `SessionPersistenceAdapter.save_session` retries `repo.save_session` (delays 0.5, 1, 2 s, permanent errors such as `ValueError` or `IntegrityError` skip the retries); any exception after that writes `{session_id}_{ts}.json` under `~/.weebot/dead_letter`, bumps a Prometheus counter and returns False (`weebot/infrastructure/persistence/session_persistence_adapter.py:37-68, 94-118, 120-155`; `weebot/config/constants.py:42`).
6. `SQLiteStateRepository.save_session` (`weebot/infrastructure/persistence/sqlite_state_repo.py:302-329`) calls `SessionQueries.save`, which drops the oldest events until `events_json` fits `MAX_EVENTS_JSON_BYTES` (10 MB, `weebot/config/constants.py:35`) but never the last plan (`_events_json`, `weebot/infrastructure/persistence/_session_queries.py:97-138`), and upserts one row (`save`, `:25-57`). `save_session_if_unchanged` writes the row only if its `updated_at` still matches (`save_if_unchanged`, `:59-81`), so a stale copy never overwrites a newer one (audit A24). Commitments and the FTS index are written afterwards in separate transactions (`sqlite_state_repo.py:346-457`).
7. Direct saves outside the publisher: routing saves before resuming into `ExecutingState` (`plan_act_flow.py:429-430`); `PlanReviewState` saves the WAITING session, then emits the question (`weebot/application/flows/states/plan_review.py:131-143`); other pauses emit, then save authoritatively (`weebot/application/flows/collaborators/user_pause.py:32-74`); `CompletedState` saves the terminal status (`weebot/application/flows/states/completed.py:318-320`); `ChatFlow._emit` saves through the adapter itself (`weebot/application/flows/chat_flow.py:71-80`); `AgentRunner` saves a new session, the session after the turn and, on resume, the session with the user's answer and the session after the resumed turn (`weebot/interfaces/cli/agent_runner.py:168, 255, 294, 326`).

### Restore
8. `flow resume <id> <answer>` (`cli/commands/flow.py:181-209`) and the interactive loop in `flow run` (`:153-173`) call `AgentRunner.resume_session`: `load_session`, require WAITING, sanitize and append the answer, save, build a new flow (`agent_runner.py:264-308`).
9. `load_session` reads the row and `_row_to_session` rebuilds the `Session` (`sqlite_state_repo.py:459-464, 481-520`).
10. `FlowRouter.resolve_initial_state` reads `session.get_last_plan()`; an incomplete plan resumes in `ExecutingState` with WAITING turned to RUNNING (`weebot/application/flows/flow_router.py:196-207`); the flow then sets `self._plan = session.get_last_plan()` (`plan_act_flow.py:421-433`).
11. `Session.get_last_plan` asks the memory index for the last `PlanEvent` and applies the status of each later `StepEvent`, with a scan fallback (`weebot/domain/models/session.py:276-311`; `weebot/domain/services/session_memory.py:23-64`). `ExecuteStepHandler` reads the plan the same way from a fresh load on every step (`weebot/application/cqrs/handlers/execute_step_handler.py:77-87`).

### Cancel across processes
12. `flow cancel <id>` first asks its own `TaskRunner` (`cli/commands/flow.py:295-297`; `agent_runner.py:362-368`). Failing that, for a RUNNING/WAITING/PENDING session it writes a marker and, unless RUNNING, sets the row FAILED (`cli/commands/flow.py:303-317`).
13. The marker is `~/.weebot/cancel/<sha256(session_id)>` (`weebot/core/cancel_requests.py:14-25`); `take` deletes it and returns True once (`:28-35`).
14. The running `PlanActFlow` calls `cancel_requests.take` at the top of every loop pass, sets FAILED, emits and yields an `ErrorEvent` and leaves the loop (`plan_act_flow.py:497-501`).

Consequences (read from source, not run):
- `AgentRunner` keeps COMPLETED, WAITING and FAILED when the flow returns and turns any other status into WAITING (`agent_runner.py:33-39, 253`), so a cancelled turn stays FAILED; a session left mid-loop reads as resumable.
- Nothing calls `replay_dead_letters` (`session_persistence_adapter.py:157`); the only mention outside the adapter is the `doctor` hint (`weebot/interfaces/cli/support.py:262-273`).
- Without an adapter a failed save is only a warning (`event_publisher.py:179-183`), which is why `pause_flow_for_user` saves directly and lets a failure surface (`user_pause.py:60-67`).
- Truncation trims the stored row, not `session.events` (`_session_queries.py:97-138`; `sqlite_state_repo.py:321-328`): the in-memory session keeps the dropped events, a reload does not.

## If you change this
**Hits:** every flow's durability and resume; `flow resume`, `flow cancel`; tests `tests/unit/fixes/test_create_flow_persistence.py`, `tests/unit/test_cqrs_persistence.py`, `tests/unit/fixes/test_audit_downgrade_is_persisted.py`, `tests/unit/fixes/test_runner_keeps_a_failed_status.py`.
**Does not hit:** the event store (`weebot/infrastructure/event_store.py`), a separate audit journal; checkpoints (`CheckpointScheduler`, `weebot/application/flows/_checkpoint_scheduler.py:30`), which are a hook, not this row.

## See
`weebot/application/flows/event_publisher.py`, `weebot/infrastructure/persistence/session_persistence_adapter.py`, `weebot/infrastructure/persistence/_session_queries.py`, `weebot/core/cancel_requests.py`
