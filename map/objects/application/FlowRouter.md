---
type: object
name: FlowRouter
code: FlowRouter
cluster: application
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# FlowRouter

Decides which `FlowState` a turn starts in, from the session's pause flags and plan status. One static method does it; `PlanActFlow.run()` calls it once per turn.

## Why this shape
Extracted from `PlanActFlow.run()` so routing is testable alone (`weebot/application/flows/flow_router.py:1-10`). It returns the state *and* a possibly changed `Session`, so the caller applies flag clearing and status changes in the same step as the transition (`:8-9`, `:31`). Resume after a human pause always goes through it, which is why the pause flags live in `session.context.extra`.

## Shape
`resolve_initial_state(session, prompt, extra)` at `flow_router.py:29`. Priority order, first match wins:

| # | Condition | Result | Lines |
|---|---|---|---|
| 0 | `_product_gate_pending` | `ProductGateState(resume_with=prompt)`, flag cleared | 48-58 |
| 1 | `plan_pending_approval` | approve token or empty → `ExecutingState` (session set RUNNING); otherwise → `PlanningState` with `_plan_modification_request` (RUNNING) | 60-92 |
| 2 | `_user_gate_pending` | approve token → flag cleared, falls through to 3/4; anything else → `PlanningState` (RUNNING), per-step `constraint_gate_ack:*` facts reset, `atomic_mail_inbound_pending` re-armed if the gate was `inbound_mail` | 103-160 |
| 3 | last plan exists and is incomplete | `ExecutingState` (WAITING → RUNNING) | 162-168 |
| 4 | session WAITING with a plan | `ExecutingState` (RUNNING) | 170-173 |
| 5 | otherwise | `PlanningState` | 175 |

Also `record_misalignment(session, prompt, journal)` at `:178`: best-effort, schedules a journal write, swallows only `ImportError` (`:196`).

Two details that look like bugs and are deliberate:
- An empty answer approves a plan (`:73`) but does **not** approve a gate (`:114-117`): gates guard untrusted input, silence is not consent.
- Every non-approve branch sets the session RUNNING because the run loop breaks on WAITING (`:75-76`, `:87-92`, `:155-159`; loop break at `plan_act_flow.py:797`).

Which plan an approve runs: the resumed flow takes the plan from the last `PlanEvent` in the session (`Session.get_last_plan`, `plan_act_flow.py:634`), not from what `PlanReviewState` showed. A state that replaces `context._plan` must emit a `PlanEvent`, or the reviewed plan and the run diverge. Fixed 2026-10-22 for DPPM (plan F36): `PlanningState` now emits `PlanEvent(status=UPDATED)` for the merged plan. `PremortmState` does the same for its risk notes (remaining-fix plan A8), and `PlanReviewState` now emits its `PlanReviewEvent` too (F37).

Known sharp edge, in the source's own words: priorities 0 and 1 build `extra_out` as `{**(extra or {}), ...}`, which drops other keys if a caller omits `extra` (`:108-111`). Priority 2 merges onto the session's own extra instead.

## Connected to
- **Called by** `PlanActFlow.run()` (`plan_act_flow.py:628`) and, for `record_misalignment`, `plan_act_flow.py:645`.
- **Reads flags written by** `executing.py:100` (`_user_gate_pending`), `plan_review.py:96` (`plan_pending_approval`), `product_gate.py:153` (`_product_gate_pending`).
- **Approve words:** `_APPROVE_TOKENS`, `states/plan_review.py:30` (imported lazily at `:63`, `:105`).
- **Not** the state machine itself: transitions *between* states are `context.set_state(...)` calls inside each state (see FlowState).

## If you change this
**Hits:** every resume path after a pause (plan approval, product gate, inbound-mail and constraint gates); the three flag writers above (a renamed key silently stops routing); tests `tests/unit/application/flows/test_user_gate_answer_is_honoured.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/unit/test_architecture_fitness.py`, `tests/integration/test_mcp_scoped_retrieval.py`, `tests/integration/test_mcp_tool_budget.py` (all reference `FlowRouter`).
**Does not hit:** `PlanActFlow.set_state` and state-to-state transitions; the iteration loop; persistence (it only returns a new `Session` object).

## Surfaces
Internal only. Reached by CLI, web and MCP indirectly through `PlanActFlow`.

## See
`weebot/application/flows/flow_router.py`
