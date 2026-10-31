---
type: object
name: PlanActFlow
code: PlanActFlow
cluster: application
universe: live
status: verified
verified: 2026-10-30
commit: 8e6d1cca
---

# PlanActFlow

The runner for one agent turn. It owns the current `FlowState`, the `Session` and the `Plan`, and loops "execute state, check stop conditions" until the session completes, fails, waits for a human, or hits the iteration cap. `run(prompt)` is an async generator that yields `AgentEvent`s.

## Why this shape
The state machine was pulled out into state classes (see FlowState) and the start-state choice into FlowRouter, so what remains here is wiring plus the loop. The file is 654 lines (was 996); `ARCHITECTURE.md:70` lists D4 (its size) as closed on 2026-10-30, after the once-per-run prologue moved to `_run_prologue.py`. The budget and termination logic left for `collaborators/session_budget.py` (plan 5). Construction takes a `PlanActFlowConfig`; the constructor is a dozen lines (`weebot/application/flows/plan_act_flow.py:59-80`) because the three jobs it used to do inline now live in `weebot/application/flows/_plan_act_wiring.py` -- the legacy keyword names at `:43`, `config_from_legacy` at `:89`, the port wiring at `:118` and the agent composition at `:212`. The legacy keywords are still accepted and are provably the config's fields (`tests/unit/application/flows/test_the_flow_is_built_from_its_config.py`).

## Shape
`run()` at `plan_act_flow.py:334` binds the session id to every log record, seeds the session cost meter (`:337-341`), then delegates to `_run_states` (`:345`), which starts with `begin_run` (`:346`). `begin_run` is the once-per-run prologue in `weebot/application/flows/_run_prologue.py:26`, in order:
1. Open the `plan_act_iteration` tracing span when OTEL tracing is enabled (`_run_prologue.py:33-49`). Remember the first non-empty prompt as `original_task` (`:51-61`).
2. Extract session-scoped constraints if an extractor is wired (`:66-67`); hydrate behavioral rules (`:70-78`).
3. `ContinuationDetector.resolve_prompt` turns vague follow-ups ("yes") into a full prompt (`:80-82`).
4. Assemble tools for this query via `ToolAssembler` (`:85-96`).
5. `FlowRouter.resolve_initial_state` picks the start state (`:99-103`). For `ExecutingState` the session is saved first (the step handler reloads the plan from the repo) and the last plan becomes `_plan` (`:104-111`). For `PlanningState` a rejected plan is recorded in the misalignment journal (`:112-124`), and with `PRODUCT_MODE_ENABLED` `ProductGateState` runs first (`:126-133`).
6. `pre_execute` hooks (`:138-142`).

Then the loop in `plan_act_flow.py`, `while iteration_count <= max_iterations` (`:377`):
7. Per iteration: a `flow cancel` request fails the session and ends the loop (`:379-383`); composable termination conditions can jump to `CompletedState` (`enforce_termination`, `:397-398`); with a cost meter, `enforce_budget` can end the run as `BUDGET_EXCEEDED` or pause it for approval (`:401-407`; both in `collaborators/session_budget.py`); the harness block is re-resolved for the configured model and pushed to the summary executor (`:411-427`); the state runs with the turn prompt, which is emptied once any state yields a non-error event (`:433-445`).
8. `PlanStuckError` yields `ErrorEvent(error_code="PLAN_STUCK")` and ends (`:446-469`). The counter `_similar_plan_count` is bumped in `_snapshot_plan` against `_MAX_SIMILAR_PLANS = 3` (`:541-575`).
9. Stops when session status is COMPLETED, WAITING or FAILED (`:472-476`), or flow status is IDLE (`:479-480`). Then `post_execute` hooks (`:484-496`) and decomposition signals (`:499`). If the cap was exceeded, yields `ErrorEvent("Max iterations ...")` (`:501-502`).

Executors: the flow builds `_summary_executor` from its settings (`_plan_act_wiring.py:269`); steps run on `ExecuteStepHandler`'s executor, which receives the flow's settings through `step_execution_context()` (ADR-015) (`plan_act_flow.py:605-614`). `record_step_usage` adds each step's token usage and skill gaps, and `token_usage` sums them with the summary executor's own (`:596-620`).

Other members: `set_state` (`:291-332`) records per-state duration metrics, updates `status` from the state's class attribute, and opens a tracing span; `_pause_for_user` (`:227-235`) delegates to `collaborators/user_pause.py`; plan undo/redo (`:578-595`).

## Connected to
- **Uses:** `FlowRouter`, `FlowState` subclasses, `PlannerAgent` (`_plan_act_wiring.py:233`), `ExecutorAgent` (`self._summary_executor`), `Mediator` and `StateRepositoryPort` (assigned by `wire_ports`, `_plan_act_wiring.py:130-131`), `ToolAssembler`, `ContinuationDetector`.
- **Constructed at:** `weebot/application/di/__init__.py:423, 696`, `weebot/application/di/_agent_tools.py:83`, `weebot/application/di/_skillopt.py:253, 331`, `weebot/application/flows/flow_builder.py:166` (the builder behind the container's `create_flow`; it moved out of `interfaces/factories.py`), `weebot/interfaces/factories.py:315`, `weebot/application/flows/harness_opt_flow.py:295`.
- **Looks like but is not:** the other flows beside it in `application/flows/` (`chat_flow.py`, `skill_opt_flow.py`, `harness_opt_flow.py`, `harness_generation_flow.py`, `hyper_agent_flow.py`), separate classes not covered by this card. `ChatFlow` reuses `IdleState`/`ChatMessageState`.

## If you change this
**Hits:** every state (they call `context.set_state` and read `context._session`, `_plan`, `_summary_executor` and other private attributes, for example `states/summarizing.py:51`, `states/completed.py:383`); the eight construction sites above; `PlanActFlowConfig` in `weebot/application/models/plan_act_flow_config.py`; `StepExecutionContext` and `ExecuteStepHandler`; `collaborators/session_budget.py` (reads `_cost_meter`, `_budget_grants`, `_termination_conditions`, `_flow_started_at`); hooks `pre_execute`/`post_execute`; the Prometheus metric `flow_step_duration_seconds`; test `tests/unit/test_plan_act_flow_session_constraints.py` and the state tests listed on the FlowState card.
**Does not hit:** FlowRouter's priority table (it takes a `Session`, not the flow); the CQRS handlers' registration; LLM adapters.

## Surfaces
CLI (`flow run/resume/cancel`), web and MCP reach it through the factories listed above. Which entry point calls which factory was not traced for this card.

## See
`weebot/application/flows/plan_act_flow.py`
