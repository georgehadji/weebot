---
type: object
name: FlowState (the Plan-Act states)
code: FlowState
cluster: application
universe: live
status: verified
verified: 2026-10-24
commit: 1a0e0052
---

# FlowState

The abstract base for one step of the Plan-Act state machine, plus the 14 state classes under `weebot/application/flows/states/`. A state is an object with one async-generator method; it moves the machine by calling `context.set_state(next)`.

## Why this shape
States are classes so each owns its status and transitions, and `PlanActFlow.set_state` needs no hard-coded table (`states/base.py:58-61`, `plan_act_flow.py:534-538`). A state gets the whole `PlanActFlow` as `context` and reaches into its private attributes (`context._session`, `context._plan`, `context._plan_critic`), so states are tightly bound to the flow, not independent units.

## Shape
- `FlowState.execute(context, prompt)` → `AsyncGenerator[AgentEvent, None]`, abstract (`base.py:55-66`). `MetaAnalysisState` is a plain coroutine instead; the run loop accepts both (`plan_act_flow.py:768-774`).
- `status: AgentStatus` class attribute (`base.py:61`); enum values idle, planning, executing, reviewing, updating, verifying, summarizing, completed (`base.py:15-25`). Several sub-states reuse `PLANNING` on purpose (`critiquing.py:35`, `plan_review.py:66`, `premortem.py:29`, `product_gate.py:90`).
- `task_text(context, prompt)` (`base.py:28`): returns the turn prompt, or falls back to `_original_task` / `last_prompt`, because the run loop empties `prompt` after the first state yields (`plan_act_flow.py:762, 771`).

Transitions, from every `set_state` call in `states/` (grep, 2026-10-21):

| From | To |
|---|---|
| Planning | Summarizing (no steps, `planning.py:237`); Critiquing (`:298`); `next_state_after_plan()` (`:302`) |
| Critiquing | `next_state_after_plan()` (`critiquing.py:53,58`); Premortem (`:109,116,125`); Planning (`:135`) |
| Premortem | `next_state_after_plan()` (`premortem.py:40,48,76`) |
| `next_state_after_plan()` | `ExecutingState` if `settings.plan_review_enabled` is false, else `PlanReviewState` (`plan_review.py:49-60`) |
| PlanReview | Executing (`:76,88`); otherwise sets WAITING and `plan_pending_approval` and pauses (`:96,108`) |
| ProductGate | Planning (`product_gate.py:102,108,215`) |
| Executing | Verifying, Updating, Executing, Planning (`executing.py:273-784`); Reviewing when `_code_reviewer` is set, the step is a code step and `retry_count < _MAX_REVIEW_RETRIES_GATE` (`:769-784`) |
| Reviewing | Executing, Updating (`reviewing.py:60-147`) |
| Updating | Executing (`updating.py:131,245`) |
| Summarizing | MetaAnalysis (`summarizing.py:54`) |
| MetaAnalysis | Verifying (`meta_analysis.py:95`) |
| Verifying | Completed (`verifying.py:69-222`) |

`IdleState` → `ChatMessageState` (`idle.py:36`) are used by `ChatFlow` (`chat_flow.py:94,118,123`), not by `PlanActFlow`.

## Connected to
- **Owned by** `PlanActFlow` (`_state`). **Entry state** chosen by FlowRouter.
- **Pause flags:** executing, plan_review and product_gate write the flags FlowRouter reads.
- Looks like but is not: `AgentState` in `weebot/domain/legacy_models.py:189` (a legacy enum; its docstring maps it to `AgentStatus`, `:19`). Use `AgentStatus` from `states/base.py`.
- Outside importers of `flows.states`: only docstring or comment mentions in `cqrs/handlers/summarize_handler.py`, `cqrs/handlers/update_plan_handler.py`, `services/background_tasks.py`, `domain/legacy_models.py` (grep; not checked whether they import at runtime).

## If you change this
**Hits:** `PlanActFlow.set_state` and `run()` (status, metrics, tracing); every state that transitions to the changed one; `next_state_after_plan` and the `plan_review_enabled` setting; tests `tests/unit/test_plan_review_state.py`, `test_premortem_state.py`, `test_reviewing_state.py`, `test_updating_state_critic.py`, `test_w3_flow_state_and_subscription.py`.
**Does not hit:** FlowRouter's priority logic (it only names `PlanningState`, `ExecutingState`, `ProductGateState`); the CQRS handlers; persistence.

## Surfaces
Internal only. Event output reaches clients through `PlanActFlow` event emission.

## See
`weebot/application/flows/states/base.py`
