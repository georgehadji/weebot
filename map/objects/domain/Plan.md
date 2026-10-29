---
type: object
name: Plan
code: Plan, PlanStatus, PlanCritique
cluster: domain
universe: live
status: stale
verified: 2026-10-29
commit: e102c98e
---

# Plan

The ordered list of `Step`s a flow runs against, plus a title, a summary and a `PlanStatus`. `PlanCritique` (same file) is the critic's verdict on a plan before execution; it lives here because it has no behaviour of its own.

## Why this shape
Immutable: every mutator returns a new `Plan` through `model_copy` (`weebot/domain/models/plan.py:197-237`), so a flow state can only change the plan by reassigning `context._plan` (`application/flows/states/executing.py:234`; `weebot/application/flows/states/_step_outcome.py:129, 186, 199, 248`). "Stop running" and "it worked" are two predicates on purpose: `is_complete()` counts FAILED steps as done (`:222-231`), `is_successful()` needs every step COMPLETED (`:233-243`). The docstring records why: three readers took `is_complete()` as success, including the template cache, which stored an all-failed plan with score 1.0 (`:236-241`).

## Shape
- `PlanStatus` (`:19-35`): `created`, `updated`, `running`, `completed`, `failed`. The comment at `:29-34` says `FAILED` is backend only and the UI type omits `running`; that is out of date: `weebot-ui/src/types/events.ts:6` lists all five values.
- `Plan` fields (`weebot/domain/models/plan.py:174-182`): `title`, `message`, `steps: list[Step]`, `status`, `heuristic_splits: int` (a field, not a private attribute, so it survives `model_dump`/`model_validate`; `:161-165`).
- Reads: `get_next_step` (first not-done step, `:167-172`), `get_pending_steps` (`:174-175`), `get_completed_steps` (`:177-178`), `failed_steps` (`:245-247`).
- Writes: `replace_step` (`:180-183`), `update_step_status` (`:185-198`), `merge` (`:200-220`): keeps done and UNVERIFIED steps, appends fresh steps from the update, drops any whose id or first 80 lowercased characters of description match a kept step; stamps `UPDATED`.
- Checks: `is_complete`, `is_successful` (above); `is_valid` (`:251-266`), `remaining_budget` (`:268-271`), `validate_step_descriptions` (`:273-286`).
- `PlanCritique` (`:124-151`): `plan_id`, `step_scores`, `degraded`, `flaws`, `suggestions`, `overall_confidence` (0..1, default 0.0), `verdict` (default `"approved"`). `degraded=True` means the critic did not run and the other fields are defaults, not a judgement (`:135-143`).

Consequences (read from source, not run):
- `is_valid`, `remaining_budget` and `validate_step_descriptions` have no caller in `weebot/` or `cli/` (grep 2026-10-24); `PlanStatus.RUNNING` is never assigned.
- `heuristic_splits` reaches the flow. The planner passes it to the constructor (`application/agents/planner.py:389-393`) and yields `plan.model_dump()` (`:271`); `PlanningState` rebuilds with `Plan.model_validate` (`application/flows/states/planning.py:270`), which keeps a field, so misalignment signal 4 in `plan_act_flow.py:396-399` can fire. Pinned by `tests/unit/fixes/test_heuristic_splits_survive.py`.
- `PlanCritique.verdict` defaults to `"approved"` (`weebot/domain/models/plan.py:168`); a consumer that ignores `degraded` reads a default as approval. `CritiquingState` checks `degraded` first (`application/flows/states/critiquing.py:96`); the critic gate in `UpdatingState` reads only `overall_confidence` (`application/flows/states/updating.py:239`).
- `step_scores` is written by the critic (`application/services/plan_critic.py:93`) and read by nothing; the critic's own comment says so (`:109`).

## Connected to
- **Owns** `Step` (see the Step card). **Built by** `PlannerAgent._parse_plan` (`application/agents/planner.py:329`) and merged by `PlannerAgent.update_plan` (`:305`). **Held by** the flow as `context._plan`; set in `PlanningState` (`planning.py:270, 288, 278`) and changed in `ExecutingState`, `ReviewingState` (`reviewing.py:145, 161`), `UpdatingState` (`updating.py:133, 214`). `CompletedState` stamps `FAILED` or `COMPLETED` from `Plan.outcome()` (`domain/models/plan.py:270`; FAILED if a step failed, INCOMPLETE if one is unverified or never ran), and INCOMPLETE ends FAILED too, per owner decision D-R1 (`completed.py:177-186`, audit R06).
- **Persisted only as events:** a `PlanEvent.plan` dict inside `Session.events`; rebuilt by `Session.get_last_plan` (Session card).
- **Scored by** `PlanOutcomeScorer` via `is_successful()` (`infrastructure/scoring/plan_outcome_scorer.py:64`).
- `PlanCritique` **produced by** `PlanCriticService` (`application/services/plan_critic.py:53`) behind `PlanCriticPort` (`application/ports/plan_critic_port.py:20`), **read by** `CritiquingState` (`critiquing.py:77-152`), `UpdatingState` (`updating.py:239`), `PlanActFlow` misalignment signals (`plan_act_flow.py:392`).
- **Looks like but is not:** legacy `Task`/`Project` dataclasses in `weebot/domain/legacy_models.py:70, 125` (still re-exported by `weebot/domain/models/__init__.py:13-26`); workflow templates in `weebot/templates/`; `CodeReviewResult` in `domain/models/code_review.py` (same shape idea, one step).

## If you change this
**Hits:** every flow state that reassigns `context._plan`, plan rebuild on resume (`Session.get_last_plan`, `SessionMemory.find_last_plan`), the UI's `PlanStatus` type (`weebot-ui/src/types/events.ts`), the template cache score. Tests: `tests/unit/application/flows/test_a_failed_plan_is_not_a_success.py`, `tests/unit/application/flows/test_quality_gates_are_loud.py`, `tests/unit/application/flows/test_user_gate_answer_is_honoured.py`, `tests/unit/infrastructure/test_plan_outcome_scoring.py`, `tests/unit/test_updating_state_critic.py`, `tests/unit/test_reliability_fixes.py`, `tests/unit/test_acr_p3.py`, `tests/unit/test_reviewing_state.py`.
**Does not hit:** `Step` status semantics (Step card); the legacy `Task` model.

## Surfaces
`PlanEvent` to the web UI and CLI; plan review pause (`PlanReviewEvent.plan_data`, `domain/models/event.py:103-112`).

## See
`weebot/domain/models/plan.py`
