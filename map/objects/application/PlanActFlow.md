---
type: object
name: PlanActFlow
code: PlanActFlow
cluster: application
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# PlanActFlow

The runner for one agent turn. It owns the current `FlowState`, the `Session` and the `Plan`, and loops "execute state, check stop conditions" until the session completes, fails, waits for a human, or hits the iteration cap. `run(prompt)` is an async generator that yields `AgentEvent`s.

## Why this shape
The state machine was pulled out into state classes (see FlowState) and the start-state choice into FlowRouter, so what remains here is wiring plus the loop. The file is still large (985 lines); `ARCHITECTURE.md:62` lists its size as known debt (D4, target 700). Construction takes a `PlanActFlowConfig`, with a long list of legacy keyword arguments kept for old call sites (`weebot/application/flows/plan_act_flow.py:76-116`, normalised at `:117-121`).

## Shape
`run()` at `plan_act_flow.py:556`, in order:
1. Open the `plan_act_iteration` tracing span when OTEL tracing is enabled (`:562-577`). Remember the first non-empty prompt as `original_task` (`:578-589`).
2. Extract session-scoped constraints if an extractor is wired (`:591-596`); hydrate behavioral rules (`:599-606`).
3. `ContinuationDetector.resolve_prompt` turns vague follow-ups ("yes") into a full prompt (`:608-611`).
4. Assemble tools for this query via `ToolAssembler` (`:613-625`).
5. `FlowRouter.resolve_initial_state` picks the start state (`:627-632`). For `ExecutingState` the session is saved first (the step handler reloads the plan from the repo) and the last plan becomes `_plan` (`:633-640`). For `PlanningState` a rejected plan is recorded in the misalignment journal (`:641-651`), and with `PRODUCT_MODE_ENABLED` `ProductGateState` runs first (`:654-662`).
6. `pre_execute` hooks (`:667-671`), then the loop `while iteration_count <= max_iterations` (`:702`).
7. Per iteration: a `flow cancel` request fails the session and ends the loop (`:704-708`); composable termination conditions can jump to `CompletedState` (`:721-740`); the harness block is re-resolved for the configured model and pushed to the summary executor (`:742-762`); the state runs with the turn prompt, which is emptied once any state yields a non-error event (`:764-779`).
8. `PlanStuckError` yields `ErrorEvent(error_code="PLAN_STUCK")` and ends (`:780-801`). The counter `_similar_plan_count` is bumped in `_snapshot_plan` against `_MAX_SIMILAR_PLANS = 3` (`:875-908`).
9. Stops when session status is COMPLETED, WAITING or FAILED (`:805-810`), or flow status is IDLE (`:812-814`). Then `post_execute` hooks (`:816-830`) and decomposition signals (`:832-833`). If the cap was exceeded, yields `ErrorEvent("Max iterations ...")` (`:835-836`).

Executors: the flow builds `_summary_executor` from its settings; steps run on `ExecuteStepHandler`'s executor, which receives the flow's settings through `step_execution_context()` (ADR-015) (`:263-294, 939-948`). `record_step_usage` adds each step's token usage and skill gaps, and `token_usage` sums them with the summary executor's own (`:930-954`).

Other members: `set_state` (`:513-554`) records per-state duration metrics, updates `status` from the state's class attribute, and opens a tracing span; `_pause_for_user` (`:451-459`) delegates to `collaborators/user_pause.py`; plan undo/redo (`:912-928`).

## Connected to
- **Uses:** `FlowRouter`, `FlowState` subclasses, `PlannerAgent` (`:255-262`), `ExecutorAgent` (`self._summary_executor`), `Mediator` and `StateRepositoryPort` (TYPE_CHECKING imports, `:59-62`), `ToolAssembler`, `ContinuationDetector`.
- **Constructed at:** `weebot/application/di/__init__.py:367, 644`, `weebot/application/di/_agent_tools.py:75`, `weebot/application/di/_skillopt.py:245, 315`, `weebot/interfaces/factories.py:274, 353`, `weebot/application/flows/harness_opt_flow.py:289`.
- **Looks like but is not:** the other flows beside it in `application/flows/` (`chat_flow.py`, `skill_opt_flow.py`, `harness_opt_flow.py`, `harness_generation_flow.py`, `hyper_agent_flow.py`), separate classes not covered by this card. `ChatFlow` reuses `IdleState`/`ChatMessageState`.

## If you change this
**Hits:** every state (they call `context.set_state` and read `context._session`, `_plan`, `_summary_executor` and other private attributes, for example `states/summarizing.py:50`, `states/completed.py:352`); the eight construction sites above; `PlanActFlowConfig` in `weebot/application/models/plan_act_flow_config.py`; `StepExecutionContext` and `ExecuteStepHandler`; hooks `pre_execute`/`post_execute`; the Prometheus metric `flow_step_duration_seconds`; test `tests/unit/test_plan_act_flow_session_constraints.py` and the state tests listed on the FlowState card.
**Does not hit:** FlowRouter's priority table (it takes a `Session`, not the flow); the CQRS handlers' registration; LLM adapters.

## Surfaces
CLI (`flow run/resume/cancel`), web and MCP reach it through the factories listed above. Which entry point calls which factory was not traced for this card.

## See
`weebot/application/flows/plan_act_flow.py`
