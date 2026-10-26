---
type: process
name: session persistence
code: EventPublisher._persist_session, SessionPersistenceAdapter, SQLiteStateRepository, cancel_requests
cluster: application
universe: live
status: stale
verified: 2026-10-23
commit: c2f39937
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
1. Every state emits through `PlanActFlow._emit`, which syncs the publisher's session and takes the mutated one back (`weebot/application/flows/plan_act_flow.py:462-480`). The publisher is built once per flow with the flow's repo and `persistence_adapter` (`:435-450`, getter `:947-953`).
2. `EventPublisher.emit`: truth binding, credential sanitization, `session.add_event`, a checkpoint hook on `step` events, bus publish and domain events, then `_persist_session` when a state repo is set (`weebot/application/flows/event_publisher.py:60-80`).
3. `_persist_session` uses the adapter when present and logs a dead-letter on `False`; without one it calls `state_repo.save_session` and logs a warning on failure (`event_publisher.py:159-170`).
4. The adapter comes from DI: `"session_persistence"` (`weebot/application/di/__init__.py:141`) builds `SessionPersistenceAdapter(repo, RetryWithBackoff(delays=[0.5, 1.0, 2.0], jitter=0.25))` (`:601-609`); `create_flow` passes it to every `PlanActFlow` and `ChatFlow` (`weebot/interfaces/factories.py:304, 318`).
5. `SessionPersistenceAdapter.save_session` retries `repo.save_session`; any exception after the retries writes `{session_id}_{ts}.json` under `./.weebot/dead_letter`, bumps a Prometheus counter and returns False (`weebot/infrastructure/persistence/session_persistence_adapter.py:94-118, 120-155`).
6. `SQLiteStateRepository.save_session` (`weebot/infrastructure/persistence/sqlite_state_repo.py:274`) calls `SessionQueries.save`, which drops the oldest events until `events_json` fits `MAX_EVENTS_JSON_BYTES` (10 MB, `weebot/config/constants.py:35`) and upserts one row (`weebot/infrastructure/persistence/_session_queries.py:25-89`).
7. Direct saves outside the publisher: `PlanReviewState` saves the WAITING session before yielding (`weebot/application/flows/states/plan_review.py:140-142`); `CompletedState` saves the terminal status (`weebot/application/flows/states/completed.py:292-295`); `AgentRunner` saves a new session, the session after the turn and the session with the user's answer (`weebot/interfaces/cli/agent_runner.py:168, 255, 283`).

### Restore
8. `flow resume <id> <answer>` (`cli/commands/flow.py:169-195`) and the interactive loop in `flow run` (`:154`) call `AgentRunner.resume_session`: `load_session`, require WAITING, sanitize and append the answer, save, build a new flow (`agent_runner.py:264-307`).
9. `load_session` reads the row and `_row_to_session` rebuilds the `Session` (`sqlite_state_repo.py:412-417, 481`).
10. `FlowRouter.resolve_initial_state` reads `session.get_last_plan()`; an incomplete plan resumes in `ExecutingState` with WAITING turned to RUNNING (`weebot/application/flows/flow_router.py:195-200`); the flow then sets `self._plan = session.get_last_plan()` (`plan_act_flow.py:633-636`).
11. `Session.get_last_plan` asks the memory index for the last `PlanEvent` and applies the status of each later `StepEvent` (`weebot/domain/models/session.py:276-311`; `weebot/domain/services/session_memory.py:23-48`). `ExecuteStepHandler` reads the plan the same way from a fresh load on every step (`weebot/application/cqrs/handlers/execute_step_handler.py:72-78`).

### Cancel across processes
12. `flow cancel <id>` first asks its own `TaskRunner` (`cli/commands/flow.py:246-249`; `agent_runner.py:362-368`). Failing that, for a RUNNING/WAITING/PENDING session it writes a marker and, unless RUNNING, sets the row FAILED (`cli/commands/flow.py:252-269`).
13. The marker is `~/.weebot/cancel/<sha256(session_id)>` (`weebot/core/cancel_requests.py:14-25`); `take` deletes it and returns True once (`:28-35`).
14. The running `PlanActFlow` calls `cancel_requests.take` at the top of every loop pass, sets FAILED, emits and yields an `ErrorEvent` and returns (`plan_act_flow.py:700-704`).

Consequences (read from source, not run):
- The DI adapter is built without `retryable=_is_transient` (`di/__init__.py:608`), so the permanent-error short-cut in `PERSISTENCE_RETRY_CONFIG` (`session_persistence_adapter.py:41-68`) is not used in production: a malformed session waits out all three delays before dead-lettering.
- `save_session`'s docstring says non-retryable errors are re-raised (`session_persistence_adapter.py:105-107`); the `except Exception` dead-letters everything (`:112-118`).
- Nothing calls `replay_dead_letters` (`session_persistence_adapter.py:157`); the dead-letter folder is relative to the working directory (`:94`).
- Oldest-first truncation can drop the only `PlanEvent` of a long session (`_session_queries.py:45-47`); `get_last_plan` then returns None and the step handler fails with `NO_PLAN_FOUND` (`execute_step_handler.py:78-82`).
- `PlanReviewState` adds the `WaitForUserEvent` itself and then emits it, and `emit` adds it again (`plan_review.py:140, 146`; `event_publisher.py:70`): the stored session holds it twice.
- A cancelled or FAILED turn is overwritten to WAITING by `AgentRunner` after the flow returns (`agent_runner.py:237-244`), so the session reads as resumable.
- The publisher is built with the flow's plan at that moment and only its session is re-synced (`plan_act_flow.py:219-226, 479`), so truth binding and checkpoint hooks read a stale plan (`event_publisher.py:94, 128`).

## If you change this
**Hits:** every flow's durability and resume; `flow resume`, `flow cancel`; tests `tests/unit/fixes/test_create_flow_persistence.py`, `tests/unit/test_cqrs_persistence.py`, `tests/unit/fixes/test_audit_downgrade_is_persisted.py`.
**Does not hit:** the event store (`weebot/infrastructure/event_store.py`), a separate audit journal; checkpoints (`CheckpointScheduler`), which are a hook, not this row.

## See
`weebot/application/flows/event_publisher.py`, `weebot/infrastructure/persistence/session_persistence_adapter.py`, `weebot/infrastructure/persistence/_session_queries.py`, `weebot/core/cancel_requests.py`
