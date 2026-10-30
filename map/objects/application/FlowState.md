---
type: object
name: FlowState (the Plan-Act states)
code: FlowState
cluster: application
universe: live
status: verified
verified: 2026-10-30
commit: 9a422252
---

# FlowState

The abstract base for one step of the Plan-Act state machine, plus the 14 state classes under `weebot/application/flows/states/`. A state is an object with one async-generator method; it moves the machine by calling `context.set_state(next)`.

## Why this shape
States are classes so each owns its status and transitions, and `PlanActFlow.set_state` needs no hard-coded table (`states/base.py:58-61`, `plan_act_flow.py:291-295`). A state gets the whole `PlanActFlow` as `context` and reaches into its private attributes (`context._session`, `context._plan`, `context._plan_critic`), so states are tightly bound to the flow, not independent units. A state names its successor by `StateId` through a registry (`new_state(StateId.X)`, `states/base.py:78-116`), so the registered states import no sibling (plan 3.6; the import cycle is gone, `tests/unit/application/flows/test_state_registry.py`). Nine classes register with `@register_state`. `CompletedState`, `MetaAnalysisState`, `ProductGateState`, `IdleState` and `ChatMessageState` do not (`StateId.COMPLETED` has no class); the code that reaches them imports them directly (`summarizing.py:24` to MetaAnalysis, `meta_analysis.py:94` to Verifying, `verifying.py:68` to Completed, `product_gate.py:96` to Planning, `idle.py:34` to ChatMessage, `_run_prologue.py:128-130` to ProductGate).

## Shape
- `FlowState.execute(context, prompt)` → `AsyncGenerator[AgentEvent, None]`, abstract (`base.py:55-66`). `MetaAnalysisState` is a plain coroutine instead; the run loop accepts both (`plan_act_flow.py:437-441`).
- `status: AgentStatus` class attribute (`base.py:61`); enum values idle, planning, executing, reviewing, updating, verifying, summarizing, completed (`base.py:15-25`). Several sub-states reuse `PLANNING` on purpose (`critiquing.py:38`, `plan_review.py:59`, `premortem.py:38`, `product_gate.py:90`).
- `task_text(context, prompt)` (`base.py:28`): returns the turn prompt, or falls back to `_original_task` / `last_prompt`, because the run loop empties `prompt` after the first state yields (`_run_prologue.py:80`, `plan_act_flow.py:433`).

Transitions, from every `set_state` call in `states/` (grep, 2026-10-24):

| From | To |
|---|---|
| Planning | Summarizing (no steps, `planning.py:293`); Critiquing (`:321`); `next_state_after_plan()` (`:324`) |
| Critiquing | `next_state_after_plan()` (`critiquing.py:54, 59`); Premortem (`:109,115,123`); Planning (`:133`) |
| Premortem | `next_state_after_plan()` (`premortem.py:48, 56, 90`) |
| `next_state_after_plan()` | `ExecutingState` if `settings.plan_review_enabled` is false, else `PlanReviewState` (`base.py:125-135`) |
| PlanReview | Executing (`plan_review.py:68,80`); otherwise sets WAITING and `plan_pending_approval` and pauses (`:94,106`) |
| ProductGate | Planning (`product_gate.py:102,108,215`) |
| Executing | Verifying, Updating, Executing, Planning (`executing.py:104`; the evidence gate, `evidence_gate.py:51,57`, sends Executing or Updating); Reviewing when `_code_reviewer` is set, the step is a code step and `retry_count < _MAX_REVIEW_RETRIES_GATE` (`weebot/application/flows/states/_step_outcome.py:383-403`) |
| Reviewing | Executing, Updating (`reviewing.py:66-164`) |
| Updating | Executing (`updating.py:138,252`) |
| Summarizing | MetaAnalysis (`summarizing.py:55`) |
| MetaAnalysis | Verifying (`meta_analysis.py:96`) |
| Verifying | Completed (`verifying.py:70-227`) |

`IdleState` → `ChatMessageState` (`idle.py:36`) are used by `ChatFlow` (`chat_flow.py:89,113,118`), not by `PlanActFlow`.

## Connected to
- **Owned by** `PlanActFlow` (`_state`). **Entry state** chosen by FlowRouter.
- **Pause flags:** executing, plan_review and product_gate write the flags FlowRouter reads.
- Looks like but is not: `AgentState` in `weebot/domain/legacy_models.py:189` (a legacy enum; its docstring maps it to `AgentStatus`, `:19`). Use `AgentStatus` from `states/base.py`.
- Outside importers of `flows.states`: only docstring or comment mentions in `cqrs/handlers/summarize_handler.py`, `cqrs/handlers/update_plan_handler.py`, `services/tool_approval.py`, `core/background_tasks.py`, `domain/legacy_models.py` (grep; not checked whether they import at runtime).

## If you change this
**Hits:** `PlanActFlow.set_state` and `run()` (status, metrics, tracing); every state that transitions to the changed one; `next_state_after_plan` and the `plan_review_enabled` setting; tests `tests/unit/test_plan_review_state.py`, `test_premortem_state.py`, `test_reviewing_state.py`, `test_updating_state_critic.py`, `test_w3_flow_state_and_subscription.py`, `application/flows/test_state_registry.py`.
**Does not hit:** FlowRouter's priority logic (it only names `PlanningState`, `ExecutingState`, `ProductGateState`); the CQRS handlers; persistence.

## Surfaces
Internal only. Event output reaches clients through `PlanActFlow` event emission.

## See
`weebot/application/flows/states/base.py`
