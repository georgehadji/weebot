---
type: object
name: FlowRouter
code: FlowRouter
cluster: application
universe: live
status: verified
verified: 2026-10-29
commit: 6c9c50f3
---

# FlowRouter

Decides which `FlowState` a turn starts in, from the session's pause flags and plan status. One static method does it; `PlanActFlow.run()` calls it once per turn.

## Why this shape
Extracted from `PlanActFlow.run()` so routing is testable alone (`weebot/application/flows/flow_router.py:1-10`). It returns the state *and* a possibly changed `Session`, so the caller applies flag clearing and status changes in the same step as the transition (`:8-9`, `:49-51`). Resume after a human pause always goes through it, which is why the pause flags live in `session.context.extra`.

## Shape
`resolve_initial_state(session, prompt, extra)` at `flow_router.py:50-223`. Priority order, first match wins:

| # | Condition | Result | Lines |
|---|---|---|---|
| 0 | `_product_gate_pending` | `ProductGateState(resume_with=prompt)`, flag cleared | 67-78 |
| 1 | `plan_pending_approval` | approve token or empty: apply a user-edited plan file, then `ExecutingState` (RUNNING); otherwise `PlanningState` with `_plan_modification_request` (RUNNING) | 80-113 |
| 2 | `_user_gate_pending` | for `tool_approval`, `record_flow_reply` decides and issues the grant; approved: flag cleared, falls through to 3/4/5; otherwise `PlanningState` (RUNNING), per-step `constraint_gate_ack:*` facts reset, `atomic_mail_inbound_pending` re-armed if the gate was `inbound_mail` | 115-193 |
| 3 | last plan exists and is incomplete | `ExecutingState` (WAITING becomes RUNNING) | 195-201 |
| 4 | session WAITING with a plan | `ExecutingState` (RUNNING) | 203-206 |
| 5 | otherwise | `PlanningState`; a WAITING session is set RUNNING. When the events hold an asked question and the prompt is not the task, the prompt is an answer to intent review: it is kept as `_clarification_answer`, and `PlanningState` plans from the task plus the answer (`with_clarification`) | 209-223 |

- `_apply_plan_file(session)`: if the user edited `Output/<session>/01_plan.md`, the edited steps become the plan as a new `PlanEvent(UPDATED)`; unchanged steps keep their ids (ICM B2) (`:25-42`, used at `:95`).
- `record_misalignment(session, prompt, journal)` (`:226-246`): best-effort, schedules a journal write, swallows only `ImportError` (`:245-246`).

Two details that look like bugs and are deliberate:
- An empty answer approves a plan (`:93`) but does **not** approve a gate (`:135-138`): gates guard untrusted input, silence is not consent.
- Every non-approve branch sets the session RUNNING because the run loop breaks on WAITING (`:96-98, 108-113, 188-193`; loop break at `weebot/application/flows/plan_act_flow.py:473-476`).

Which plan an approve runs: the resumed flow takes the plan from the last `PlanEvent` in the session (`Session.get_last_plan`, `weebot/application/flows/_run_prologue.py:109`), not from what `PlanReviewState` showed. A state that replaces `context._plan` must emit a `PlanEvent`, or the reviewed plan and the run diverge. `PlanningState` emits one for the DPPM plan (`weebot/application/flows/states/planning.py:313-315`, F36), `PremortemState` for its risk notes (`states/premortem.py:74`), and `PlanReviewState` emits its `PlanReviewEvent` (`states/plan_review.py:87`, F37).

Known sharp edge, in the source's own words: priorities 0 and 1 build `extra_out` as `{**(extra or {}), ...}` (`:73, 88`), which erases other keys if a caller omits `extra` (`:129-132`). Priority 2 merges onto the session's own extra instead (`:133`). The one production caller passes `extra` (`_run_prologue.py:102`).

## Connected to
- **Called by** `begin_run`, the prologue of `PlanActFlow._run_states` (`weebot/application/flows/_run_prologue.py:99-103`) and, for `record_misalignment`, `_run_prologue.py:120`.
- **Reads flags written by** `states/_execution_gates.py:54` (`_user_gate_pending`), `weebot/application/services/tool_approval.py:314-326` (`_user_gate_pending = "tool_approval"`), `states/plan_review.py:94` (`plan_pending_approval`), `states/product_gate.py:153` (`_product_gate_pending`).
- **Approve words:** `_APPROVE_TOKENS`, `states/plan_review.py:36` (imported lazily at `flow_router.py:84, 127`).
- **Not** the state machine itself: transitions *between* states are `context.set_state(...)` calls inside each state (see FlowState).

## If you change this
**Hits:** every resume path after a pause (plan approval, product gate, inbound-mail, constraint and tool-approval gates); the flag writers above (a renamed key silently stops routing); `tool_approval.record_flow_reply` grants; tests `tests/unit/application/flows/test_user_gate_answer_is_honoured.py`, `tests/e2e/test_gate_pause_survives_the_seam.py`, `tests/unit/test_architecture_fitness.py`, `tests/integration/test_mcp_scoped_retrieval.py`, `tests/integration/test_mcp_tool_budget.py` (all reference `FlowRouter`).
**Does not hit:** `PlanActFlow.set_state` and state-to-state transitions; the iteration loop; persistence (it only returns a new `Session` object; the flow saves it, `_run_prologue.py:108`).

## Surfaces
Internal only. Reached by CLI, web and MCP indirectly through `PlanActFlow`. The plan file at `Output/<session>/01_plan.md` is a human-editable input.

## See
`weebot/application/flows/flow_router.py`
