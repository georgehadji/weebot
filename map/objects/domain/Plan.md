---
type: object
name: Plan
code: Plan, PlanStatus, PlanCritique
cluster: domain
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# Plan

The ordered list of `Step`s a flow runs against, plus a title, a summary and a `PlanStatus`. `PlanCritique` (same file) is the critic's verdict on a plan before execution; it lives here because it has no behaviour of its own.

## Why this shape
Immutable: every mutator returns a new `Plan` through `model_copy` (`weebot/domain/models/plan.py:197-237`), so a flow state can only change the plan by reassigning `context._plan` (`application/flows/states/executing.py:240`; `weebot/application/flows/states/_step_outcome.py:129, 143, 186, 237, 291`). "Stop running" and "it worked" are two predicates on purpose: `is_complete()` counts FAILED steps as done (`weebot/domain/models/plan.py:239-248`), `is_successful()` needs every step COMPLETED by its own work (`Step.did_work`, `weebot/domain/models/plan.py:93-95, 250-260`). The docstring records why: three readers took `is_complete()` as success, including the template cache, which stored an all-failed plan with score 1.0 (`weebot/domain/models/plan.py:253-258`).

## Shape
- `PlanStatus` (`weebot/domain/models/plan.py:24-40`): `created`, `updated`, `running`, `completed`, `failed`. The comment at `weebot/domain/models/plan.py:34-39` says `FAILED` is backend only and the UI type omits `running`; that is out of date: `weebot-ui/src/types/events.ts:6` lists all five values.
- `PlanOutcome` (`weebot/domain/models/plan.py:43-48`): `succeeded`, `failed`, `incomplete`, returned by `outcome()` (audit R06).
- `Plan` fields (`weebot/domain/models/plan.py:174-182`): `title`, `message`, `steps: list[Step]`, `status`, `heuristic_splits: int` (a field, not a private attribute, so it survives `model_dump`/`model_validate`; `weebot/domain/models/plan.py:178-181`).
- Reads: `get_next_step` (first not-done step, `weebot/domain/models/plan.py:184-189`), `get_pending_steps` (`weebot/domain/models/plan.py:191-192`), `get_completed_steps` (`weebot/domain/models/plan.py:194-195`), `failed_steps` (`weebot/domain/models/plan.py:262-264`), `unfinished_steps` (`weebot/domain/models/plan.py:266-268`).
- Writes: `replace_step` (`weebot/domain/models/plan.py:197-200`), `update_step_status` (`weebot/domain/models/plan.py:202-215`), `merge` (`weebot/domain/models/plan.py:217-237`): keeps done and UNVERIFIED steps, appends fresh steps from the update, drops any whose id or first 80 lowercased characters of description match a kept step; stamps `UPDATED`.
- Checks: `is_complete`, `is_successful` (above); `outcome` (FAILED if a step failed, INCOMPLETE if one is unverified or never ran, `weebot/domain/models/plan.py:270-276`); `is_valid` (`weebot/domain/models/plan.py:280-295`), `remaining_budget` (`weebot/domain/models/plan.py:297-300`), `validate_step_descriptions` (`weebot/domain/models/plan.py:302-315`).
- `PlanCritique` (`weebot/domain/models/plan.py:141-168`): `plan_id`, `step_scores`, `degraded`, `flaws`, `suggestions`, `overall_confidence` (0..1, default 0.0), `verdict` (default `"approved"`). `degraded=True` means the critic did not run and the other fields are defaults, not a judgement (`weebot/domain/models/plan.py:152-160`).

Consequences (read from source, not run):
- `is_valid`, `remaining_budget` and `validate_step_descriptions` have no caller in `weebot/` or `cli/` (grep 2026-10-30); `PlanStatus.RUNNING` is never set on a `Plan`, only a checkpoint `PlanEvent` carries it (`application/flows/_checkpoint_scheduler.py:78`).
- `heuristic_splits` reaches the flow. The planner passes it to the constructor (`application/agents/planner.py:392-397`) and yields `plan.model_dump()` (`weebot/application/agents/planner.py:283`); `PlanningState` rebuilds with `Plan.model_validate` (`application/flows/states/planning.py:270`), which keeps a field, so misalignment signal 4 in `plan_act_flow.py:158-161` can fire. Pinned by `tests/unit/fixes/test_heuristic_splits_survive.py`.
- `PlanCritique.verdict` defaults to `"approved"` (`weebot/domain/models/plan.py:168`); a consumer that ignores `degraded` reads a default as approval. `CritiquingState` checks `degraded` first (`application/flows/states/critiquing.py:96`); the critic gate in `UpdatingState` reads only `overall_confidence` (`application/flows/states/updating.py:239`).
- `step_scores` is written by the critic (`application/services/plan_critic.py:93`) and read by nothing; the critic's own comment says so (`weebot/application/services/plan_critic.py:109`).

## Connected to
- **Owns** `Step` (see the Step card). **Built by** `PlannerAgent._parse_plan` (`application/agents/planner.py:333`) and merged by `PlannerAgent.update_plan` (`weebot/application/agents/planner.py:285`, merge at `weebot/application/agents/planner.py:312`). **Held by** the flow as `context._plan`; set in `PlanningState` (`planning.py:270, 288, 319`) and changed in `ExecutingState`, `ReviewingState` (`reviewing.py:145, 161`), `UpdatingState` (`updating.py:133, 214`). `CompletedState` stamps `FAILED` or `COMPLETED` from `Plan.outcome()` (`domain/models/plan.py:270-276`), and INCOMPLETE ends FAILED too, per owner decision D-R1 (`completed.py:177-189`, audit R06).
- **Persisted only as events:** a `PlanEvent.plan` dict inside `Session.events`; rebuilt by `Session.get_last_plan` (Session card).
- **Scored by** `PlanOutcomeScorer` via `is_successful()` (`infrastructure/scoring/plan_outcome_scorer.py:64`).
- `PlanCritique` **produced by** `PlanCriticService` (`application/services/plan_critic.py:39`) behind `PlanCriticPort` (`application/ports/plan_critic_port.py:11`), **read by** `CritiquingState` (`critiquing.py:77-152`), `UpdatingState` (`updating.py:239`), `PlanActFlow` misalignment signals (`plan_act_flow.py:152-156`).
- **Looks like but is not:** legacy `Task`/`Project` dataclasses in `weebot/domain/legacy_models.py:70, 125` (still re-exported by `weebot/domain/models/__init__.py:13-27`); workflow templates in `weebot/templates/`; `CodeReviewResult` in `domain/models/code_review.py` (same shape idea, one step).

## If you change this
**Hits:** every flow state that reassigns `context._plan`, plan rebuild on resume (`Session.get_last_plan`, `SessionMemory.find_last_plan`), the UI's `PlanStatus` type (`weebot-ui/src/types/events.ts`), the template cache score. Tests: `tests/unit/application/flows/test_a_failed_plan_is_not_a_success.py`, `tests/unit/application/flows/test_quality_gates_are_loud.py`, `tests/unit/application/flows/test_user_gate_answer_is_honoured.py`, `tests/unit/infrastructure/test_plan_outcome_scoring.py`, `tests/unit/test_updating_state_critic.py`, `tests/unit/test_reliability_fixes.py`, `tests/unit/test_acr_p3.py`, `tests/unit/test_reviewing_state.py`.
**Does not hit:** `Step` status semantics (Step card); the legacy `Task` model.

## Surfaces
`PlanEvent` to the web UI and CLI; plan review pause (`PlanReviewEvent.plan_data`, `domain/models/event.py:103-112`).

## See
`weebot/domain/models/plan.py`
