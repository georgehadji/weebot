---
type: object
name: Step
code: Step, StepStatus, ContextScope
cluster: domain
universe: live
status: verified
verified: 2026-10-29
commit: 83c1f712
---

# Step

One unit of work inside a `Plan`: an id, a description, a status and a result. `StepStatus` is its lifecycle; `ContextScope` says which prompt sources the executor loads for it.

## Why this shape
A step is a value, not an entity: the flow replaces it inside the plan (`Plan.replace_step`, `Plan.update_step_status`) instead of mutating it. `UNVERIFIED` exists because "the executor did not error" and "the evidence supports completion" are different facts (`weebot/domain/models/plan.py:21, 108-115`). `ContextScope` is the ICM stage-scoped context idea: a shell step does not need the user profile (`:38-50`).

## Shape
- `StepStatus` (`:10-16`): `pending`, `running`, `started`, `completed`, `failed`, `unverified`. `STARTED` appears only on `StepEvent` (`application/agents/executor/_base.py:554`, default at `domain/models/event.py:65`); plans use `RUNNING`.
- `ContextScope` (`:38-50`): `full` (default), `minimal`, `skill`, `creative`.
- `Step` fields (`:56-75`): `id`, `description`, `status`, `result`, `retry_count` (cap 1), `acceptance_criteria`, `evidence_refs`, `context_scope`.
- `is_done()` (`:77-78`): COMPLETED **or FAILED**. UNVERIFIED is not done, so `Plan.get_next_step` returns it again.
- `mark_running`, `mark_completed`, `mark_failed`, `mark_unverified` (`:80-110`), `is_blocked` (`:112-121`).

Consequences (read from source, not run):
- The four `mark_*` methods and `is_blocked` have no caller in `weebot/`, `cli/` or `tests/` (grep 2026-10-24; the `mark_running`/`mark_failed` hits are the legacy `Task` in `domain/legacy_models.py`). The flow sets status through `Plan.update_step_status` and `model_copy` instead (`weebot/application/flows/states/executing.py:234`, `weebot/application/flows/states/_step_outcome.py:186, 291`, `weebot/application/flows/states/evidence_gate.py:42-56`).
- `evidence_refs` is written only by the dead `mark_completed`/`mark_unverified` and read by nothing.
- `acceptance_criteria` is asked for in the planner prompt (`weebot/config/prompts/planner_system.txt:15, 56`) and parsed (`application/agents/planner.py:339-384`); no Python code reads it afterwards. It reaches a model only if a prompt serialises the whole step.
- `retry_count` is the one retry budget shared by three gates: failure severity `minor_fix` (`weebot/application/flows/states/_step_outcome.py:123-131`), step validation (`weebot/application/flows/states/_step_outcome.py:211-238`), the evidence audit (`evidence_gate.py:42-49`); review has its own cap on the same field (`application/flows/states/reviewing.py:70, 137`). A step retried by one gate has no retry left for the next.
- The `minor_fix` retry puts the step back as PENDING through `Plan.replace_step` (`weebot/application/flows/states/_step_outcome.py:129`). The severity is classified from the reconstructed `ErrorEvent` (`weebot/application/flows/states/_step_outcome.py:164-172`); until 2026-10-24 it read raw dicts, so every failure went to UPDATING and the `update_step` call that crashed was never reached (`tests/unit/fixes/test_minor_fix_retry_and_list_projects.py`).
- `ContextScope` values are copied as plain strings into `_SCOPE_SOURCES` (`application/agents/executor/_prompt_builder.py:16-19`); the executor passes `.value` (`_base.py:663-669`). A new enum member falls back to `full` silently (`_prompt_builder.py:111`).

## Connected to
- **Owned by** `Plan.steps`. **Created by** `PlannerAgent._parse_plan` (`planner.py:329-393`), which also parses `context_scope` with a fallback to FULL (`:340-342`).
- **Run by** `ExecutorAgent`, which yields `StepEvent` STARTED / FAILED / COMPLETED (`_base.py:554, 725, 721`).
- **Status mirrored in** `StepEvent.status` and rebuilt on resume from those events (Session card).
- **Looks like but is not:** `TodoEvent` (agent self-reported checklist, free-string status, `domain/models/event.py:177-185`). The UI's `StepStatus` (`weebot-ui/src/types/events.ts:7-14`) mirrors the six backend values plus a legacy `error`.

## If you change this
**Hits:** `Plan.merge` dedup and retention (UNVERIFIED handling), `Plan.is_complete`/`is_successful`, executor prompt scoping, resume reconciliation maps (`domain/models/session.py:301-306`, `domain/services/session_memory.py:54-59`), the UI step type. Tests: `tests/unit/test_prompt_builder_scope.py`, `tests/unit/test_reviewing_state.py`, `tests/unit/application/flows/test_a_failed_plan_is_not_a_success.py`, `tests/unit/application/flows/test_a_failed_plan_update_is_not_progress.py`, `tests/unit/infrastructure/test_plan_outcome_scoring.py`.
**Does not hit:** legacy `TaskStatus` (`domain/legacy_models.py:53`); `TodoEvent`.

## Surfaces
`StepEvent` stream in the web UI and CLI event logger.

## See
`weebot/domain/models/plan.py`
