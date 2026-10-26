---
type: object
name: PlanActFlow
code: PlanActFlow
cluster: application
universe: live
status: stale
verified: 2026-10-25
commit: 9dca8292
---

# PlanActFlow

The runner for one agent turn. It owns the current `FlowState`, the `Session` and the `Plan`, and loops "execute state, check stop conditions" until the session completes, fails, waits for a human, or hits the iteration cap. `run(prompt)` is an async generator that yields `AgentEvent`s.

## Why this shape
The state machine was pulled out into state classes (see FlowState) and the start-state choice into FlowRouter, so what remains here is wiring plus the loop. The file is 767 lines (was 996); `ARCHITECTURE.md:65` lists its size as known debt (D4, target 700). The budget and termination logic left for `collaborators/session_budget.py` (plan 5). Construction takes a `PlanActFlowConfig`; the constructor is 18 lines (`weebot/application/flows/plan_act_flow.py:79-97`) because the three jobs it used to do inline now live in `weebot/application/flows/_plan_act_wiring.py` -- the legacy keyword names at `:43-81`, `config_from_legacy` at `:83`, the port wiring at `:112` and the agent composition at `:197`. The legacy keywords are still accepted and are provably the config's fields (`tests/unit/application/flows/test_the_flow_is_built_from_its_config.py`).

## Shape
`run()` at `plan_act_flow.py:340` binds the session id to every log record, seeds the session cost meter (`:566-574`), then delegates to `_run_states` (`:576`), in order:
1. Open the `plan_act_iteration` tracing span when OTEL tracing is enabled (`:588-597`). Remember the first non-empty prompt as `original_task` (`:598-609`).
2. Extract session-scoped constraints if an extractor is wired (`:611-617`); hydrate behavioral rules (`:619-626`).
3. `ContinuationDetector.resolve_prompt` turns vague follow-ups ("yes") into a full prompt (`:628-631`).
4. Assemble tools for this query via `ToolAssembler` (`:633-645`).
5. `FlowRouter.resolve_initial_state` picks the start state (`:647-652`). For `ExecutingState` the session is saved first (the step handler reloads the plan from the repo) and the last plan becomes `_plan` (`:653-660`). For `PlanningState` a rejected plan is recorded in the misalignment journal (`:661-671`), and with `PRODUCT_MODE_ENABLED` `ProductGateState` runs first (`:674-680`).
6. `pre_execute` hooks (`:687-691`), then the loop `while iteration_count <= max_iterations` (`:722`).
7. Per iteration: a `flow cancel` request fails the session and ends the loop (`:724-728`); composable termination conditions can jump to `CompletedState` (`enforce_termination`, `:742-743`); with a cost meter, `enforce_budget` can end the run as `BUDGET_EXCEEDED` or pause it for approval (`:745-751`; both in `collaborators/session_budget.py`); the harness block is re-resolved for the configured model and pushed to the summary executor (`:753-773`); the state runs with the turn prompt, which is emptied once any state yields a non-error event (`:775-790`).
8. `PlanStuckError` yields `ErrorEvent(error_code="PLAN_STUCK")` and ends (`:791-812`). The counter `_similar_plan_count` is bumped in `_snapshot_plan` against `_MAX_SIMILAR_PLANS = 3` (`:887-921`).
9. Stops when session status is COMPLETED, WAITING or FAILED (`:818-821`), or flow status is IDLE (`:824-825`). Then `post_execute` hooks (`:827-841`) and decomposition signals (`:843-844`). If the cap was exceeded, yields `ErrorEvent("Max iterations ...")` (`:846-847`).

Executors: the flow builds `_summary_executor` from its settings; steps run on `ExecuteStepHandler`'s executor, which receives the flow's settings through `step_execution_context()` (ADR-015) (`:272-303, 950-959`). `record_step_usage` adds each step's token usage and skill gaps, and `token_usage` sums them with the summary executor's own (`:941-965`).

Other members: `set_state` (`:522-563`) records per-state duration metrics, updates `status` from the state's class attribute, and opens a tracing span; `_pause_for_user` (`:460-468`) delegates to `collaborators/user_pause.py`; plan undo/redo (`:923-931`).

## Connected to
- **Uses:** `FlowRouter`, `FlowState` subclasses, `PlannerAgent` (`:264-271`), `ExecutorAgent` (`self._summary_executor`), `Mediator` and `StateRepositoryPort` (TYPE_CHECKING imports, `:62-65`), `ToolAssembler`, `ContinuationDetector`.
- **Constructed at:** `weebot/application/di/__init__.py:398, 668`, `weebot/application/di/_agent_tools.py:76`, `weebot/application/di/_skillopt.py:245, 315`, `weebot/application/flows/flow_builder.py:126` (the builder behind the container's `create_flow`; it moved out of `interfaces/factories.py`), `weebot/interfaces/factories.py:279`, `weebot/application/flows/harness_opt_flow.py:289`.
- **Looks like but is not:** the other flows beside it in `application/flows/` (`chat_flow.py`, `skill_opt_flow.py`, `harness_opt_flow.py`, `harness_generation_flow.py`, `hyper_agent_flow.py`), separate classes not covered by this card. `ChatFlow` reuses `IdleState`/`ChatMessageState`.

## If you change this
**Hits:** every state (they call `context.set_state` and read `context._session`, `_plan`, `_summary_executor` and other private attributes, for example `states/summarizing.py:51`, `states/completed.py:358`); the eight construction sites above; `PlanActFlowConfig` in `weebot/application/models/plan_act_flow_config.py`; `StepExecutionContext` and `ExecuteStepHandler`; `collaborators/session_budget.py` (reads `_cost_meter`, `_budget_grants`, `_termination_conditions`, `_flow_started_at`); hooks `pre_execute`/`post_execute`; the Prometheus metric `flow_step_duration_seconds`; test `tests/unit/test_plan_act_flow_session_constraints.py` and the state tests listed on the FlowState card.
**Does not hit:** FlowRouter's priority table (it takes a `Session`, not the flow); the CQRS handlers' registration; LLM adapters.

## Surfaces
CLI (`flow run/resume/cancel`), web and MCP reach it through the factories listed above. Which entry point calls which factory was not traced for this card.

## See
`weebot/application/flows/plan_act_flow.py`
