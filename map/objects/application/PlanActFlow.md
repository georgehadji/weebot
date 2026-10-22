---
type: object
name: PlanActFlow
code: PlanActFlow
cluster: application
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# PlanActFlow

The runner for one agent turn. It owns the current `FlowState`, the `Session` and the `Plan`, and loops "execute state, check stop conditions" until the session completes, waits for a human, or hits the iteration cap. `run(prompt)` is an async generator that yields `AgentEvent`s.

## Why this shape
The state machine was pulled out into state classes (see FlowState) and the start-state choice into FlowRouter, so what remains here is wiring plus the loop. The file is still large (961 lines); `ARCHITECTURE.md` lists its size as known debt (D4, target ≤700). Construction takes a `PlanActFlowConfig`, with a long list of legacy keyword arguments kept for old call sites (`weebot/application/flows/plan_act_flow.py:76-112`, normalised at `:113-117`).

## Shape
`run()` at `plan_act_flow.py:556`, in order:
1. Remember the first non-empty prompt as `original_task` (`:580-589`).
2. Extract session-scoped constraints if an extractor is wired (`:595-596`); hydrate behavioral rules (`:602-606`).
3. `ContinuationDetector.resolve_prompt` turns vague follow-ups ("yes") into a full prompt (`:609-611`).
4. Assemble tools for this query via `ToolAssembler` (`:614-625`).
5. `FlowRouter.resolve_initial_state` picks the start state (`:628-632`). If it is `PlanningState` and `PRODUCT_MODE_ENABLED`, `ProductGateState` is inserted first (`:650-658`); a rejected plan is recorded in the misalignment journal (`:639-647`).
6. `pre_execute` hooks (`:663-667`), then the loop `while iteration_count <= max_iterations` (`:698`).
7. Per iteration: composable termination conditions can jump to `CompletedState` (`:713-730`); the harness block is re-resolved for the configured model (`:737-752`); the state runs with the turn prompt, which is emptied once any state yields a non-error event (`:757-769`).
8. `PlanStuckError` → yields `ErrorEvent(error_code="PLAN_STUCK")` and ends (`:770-792`). The counter `_similar_plan_count` is bumped in `_snapshot_plan` (`:879`) against `_MAX_SIMILAR_PLANS` (`:880`).
9. Stops when session status is COMPLETED or WAITING (`:797`), or flow status is IDLE (`:801`). Then `post_execute` hooks (`:804-818`) and decomposition signals (`:821`). If the cap was exceeded, yields `ErrorEvent("Max iterations ...")` (`:823-824`).

Other members: `set_state` (`:513`) records per-state duration metrics, updates `status` from the state's class attribute, and opens a tracing span; `_pause_for_user` (`:432`) delegates to `collaborators/user_pause.py`; plan undo/redo (`:899-914`); `token_usage` (`:918`).

## Connected to
- **Uses:** `FlowRouter`, `FlowState` subclasses, `ExecutorAgent` (`self._executor`), `Mediator` and `StateRepositoryPort` (TYPE_CHECKING imports, `:59-62`), `PlanCriticService`, `TruthBinder`, `ContinuationDetector`.
- **Constructed at:** `application/di/__init__.py:356,610`, `application/di/_agent_tools.py:73`, `application/di/_skillopt.py:242,312`, `interfaces/factories.py:188,255`, `application/flows/harness_opt_flow.py:289`.
- **Looks like but is not:** the other flows beside it in `application/flows/` (`chat_flow.py`, `skill_opt_flow.py`, `harness_opt_flow.py`, `harness_generation_flow.py`, `hyper_agent_flow.py`) — separate classes, not covered by this card. `ChatFlow` reuses `IdleState`/`ChatMessageState`.

## If you change this
**Hits:** every state (they call `context.set_state` and read `context._session`, `_plan`, `_executor` and other private attributes); the eight construction sites above; `PlanActFlowConfig` in `application/models/plan_act_flow_config.py`; hooks `pre_execute`/`post_execute`; the Prometheus metric `flow_step_duration_seconds`; test `tests/unit/test_plan_act_flow_session_constraints.py` and the state tests listed on the FlowState card.
**Does not hit:** FlowRouter's priority table (it takes a `Session`, not the flow); the CQRS handlers; LLM adapters.

## Surfaces
CLI (`flow run/resume`), web and MCP reach it through the factories listed above. Which entry point calls which factory was not traced for this card.

## See
`weebot/application/flows/plan_act_flow.py`
