---
type: process
name: flow run turn
code: cli flow run -> AgentRunner.run_prompt -> PlanActFlow.run
cluster: interfaces
universe: live
status: verified
verified: 2026-10-23
commit: c2f39937
consumes:
  - ../objects/interfaces/CLI.md
  - ../objects/application/DIContainer.md
  - ../objects/application/PlanActFlow.md
  - ../objects/application/FlowRouter.md
  - ../objects/application/FlowState.md
  - ../objects/application/Mediator.md
  - ../objects/application/PlannerAgent.md
  - ../objects/application/ExecutorAgent.md
  - ../objects/application/CascadeExecutor.md
  - ../objects/tools/BaseTool.md
  - ../objects/tools/RoleBasedToolRegistry.md
  - ../objects/domain/Session.md
  - ../objects/domain/Plan.md
  - ../objects/domain/Step.md
produces:
  - ../objects/domain/Event.md
  - ../objects/domain/Session.md
  - ../objects/infrastructure/SQLiteStateRepository.md
  - ../objects/infrastructure/EventBus.md
---

# flow run turn

**Input:** `python -m cli.main flow run "<prompt>"` (optional `--session-id`, `--model`).
**Movement:** CLI builds an `AgentRunner`, which builds tools and a `PlanActFlow`; the flow loops states Planning, PlanReview, Executing (one step per pass), Reviewing, Verifying, Completed, persisting every emitted event.
**Output:** `AgentEvent`s streamed to the terminal; the `Session` row saved with the plan, events and final status.

Line numbers include uncommitted edits in the working tree on 2026-10-23 (`tool_scope.py`, `_base.py`, `plan_review.py`, `flow_router.py`).

## Steps
1. **CLI.** `_run_async` installs `ConsoleApproval` when stdin is a TTY (`cli/commands/flow.py:51-56`). `flow_run` (`:105`) builds the LLM from `ModelSelectionService` (`:111-112`), takes state repo and `Mediator` from the shared container (`:113-114`, `_get_state_repo` `:79-85`), and builds `AgentRunner` with `event_bus=_container.get(EventBusPort)` (`:116-125`).
2. **Session.** `AgentRunner.run_prompt` (`weebot/interfaces/cli/agent_runner.py:103`) loads the session if an id was given (`:122`), else creates one and saves it (`:146-152`).
3. **Tools.** `_ensure_tools` calls `build_tools(role="admin")` once per runner (`agent_runner.py:75-79`); see [mcp-tool-loading](mcp-tool-loading.md) for what goes in and [tool-call-guard-chain](tool-call-guard-chain.md) for the wrapping.
4. **Flow.** Without a router, `create_flow("plan_act", ...)` (`agent_runner.py:205-216`). `create_flow` (`weebot/interfaces/factories.py:204`) fills a missing mediator and event bus from DI (`:230-241`), resolves optional collaborators with `_cached` (`:244-273`, `_cached` `:60-68`), and builds `PlanActFlow` with `persistence_adapter=_cached("session_persistence")` (`:274-305`).
5. **Turn prologue.** `PlanActFlow.run` (`weebot/application/flows/plan_act_flow.py:556`): remember the original task (`:580-589`), extract session constraints (`:595-596`), resolve vague follow-ups with `ContinuationDetector` (`:609-611`), run `ToolAssembler.assemble` (`:614-625`; it returns the tools unchanged when no `mcp_bridge` is wired, `weebot/application/flows/collaborators/tool_assembler.py:53-54`, and `create_flow` passes none).
6. **Start state.** `FlowRouter.resolve_initial_state` (`plan_act_flow.py:628-632`; `weebot/application/flows/flow_router.py:49`). An approved pending plan or an incomplete last plan gives `ExecutingState` (`flow_router.py:80-99, 195-200`) and the flow loads `session.get_last_plan()` (`plan_act_flow.py:633-636`); otherwise `PlanningState`, or `ProductGateState` first when `PRODUCT_MODE_ENABLED` (`:651-658`).
7. **Loop.** `while iteration_count <= max_iterations` (`plan_act_flow.py:698`). Each pass: a cross-process cancel marker ends the turn (`:700-704`, see [session-persistence](session-persistence.md)); termination conditions may set `CompletedState` and return (`:718-735`); the state runs with the turn prompt until a state yields a non-error event (`:762-773`). The loop breaks on session COMPLETED or WAITING (`:802-803`) or flow status IDLE (`:806-807`).
8. **Planning.** `PlanningState.execute` sends `CreatePlanCommand` through the mediator (`weebot/application/flows/states/planning.py:200-208`), emits and yields the reconstructed events and takes the plan from the CREATED `PlanEvent` (`:217-221`). No steps: `SummarizingState` (`:240-245`). Otherwise `CritiquingState` when a critic is wired (`:311-315`), else `next_state_after_plan()` (`:317-319`).
9. **Plan review (pause).** `next_state_after_plan` returns `PlanReviewState` when `plan_review_enabled` (default true, `weebot/config/settings.py:342-346`), else `ExecutingState` (`weebot/application/flows/states/plan_review.py:49-60`). The state emits `PlanReviewEvent` (`:98`), sets `plan_pending_approval` (`:102-104`) and WAITING (`:114`), writes the plan to an editable file (`:117-127`), adds the `WaitForUserEvent`, saves the session directly (`:140-142`), emits it (`:146`) and yields it (`:150`). The loop breaks on WAITING.
10. **Plan review (resume).** The CLI breaks on `WaitForUserEvent`, reads an answer with `asyncio.to_thread(input)` and calls `runner.resume_session` (`cli/commands/flow.py:130-159`); EOF leaves the session WAITING (`:144-152`). `resume_session` requires WAITING (`agent_runner.py:268-272`), sanitizes and appends the answer, saves (`:274-283`), builds a new flow and runs it with the answer (`:286-299`). `FlowRouter` routes an approve token to `ExecutingState` after applying an edited plan file (`flow_router.py:92-99`), anything else to `PlanningState` with the text as `_plan_modification_request` (`:100-113`).
11. **Executing (one step per pass).** `ExecutingState.execute` (`weebot/application/flows/states/executing.py:273`): no next step goes to `VerifyingState` (`:281-285`); a pending inbound-mail flag pauses through `ExecApprovalPolicy` first (`:296-311`). The step is marked RUNNING (`:415`) and `ExecuteStepCommand` is sent with the flow's `StepExecutionContext` (`:455-465`; context built at `plan_act_flow.py:931-939`).
12. **Step handler.** `ExecuteStepHandler.handle` reloads the session from the repo and takes the step from `get_last_plan()` (`weebot/application/cqrs/handlers/execute_step_handler.py:72-94`), builds an `ExecutorAgent` through the DI factory (`:97-101`; `weebot/application/di/__init__.py:529-539`, `step_executor` `:425-464`), and collects every event of `executor.execute_step` (`execute_step_handler.py:139-143`).
13. **ExecutorAgent.execute_step** (`weebot/application/agents/executor/_base.py:520`): sets the step context on the tool executor (`:545`), then per-step tool scoping: `_scope_tools_for` calls `select_tools(step.description, ...)` and `ToolCollection.set_visible` (`:499-517`; `weebot/application/services/tool_scope.py:106-119`; on by default, `WEEBOT_TOOL_SCOPE`, `weebot/config/feature_flags.py:198`). Hidden tools stay callable and are named in a system-prompt note (`_base.py:546, 694, 712`; `weebot/application/models/tool_collection.py:149-156, 158-163`). The tool loop runs `while self._step_budget.consume()` (`_base.py:674`) and calls `CascadeExecutor.call_with_cascade` (`:734-736`; [model-cascade](model-cascade.md)), then runs tool calls as a batch (`:814-843`; [tool-call-guard-chain](tool-call-guard-chain.md)).
14. **Back in ExecutingState.** Usage is added to the flow (`executing.py:474`, `plan_act_flow.py:941-945`); each event is emitted and yielded (`executing.py:480-483`); a `ToolApprovalEvent` marks the pending approval (`:484-489`). The evidence gate runs before completion (`:685-690`): `evidence_gate` asks `step_audit_service.audit_step`; on a gap the step is retried once, then marked UNVERIFIED and sent to `UpdatingState`, and a `PlanEvent` is emitted (`weebot/application/flows/states/evidence_gate.py:28-63`). Otherwise the step is marked COMPLETED (`executing.py:693-695`), memory is compacted (`:754`), and the next state is `VerifyingState` (no step left, `:758-761`), `ReviewingState` (code reviewer wired and a code step, `:766-779`) or `ExecutingState` (`:780-781`).
15. **Reviewing.** With no reviewer it passes straight back to `ExecutingState` (`weebot/application/flows/states/reviewing.py:58-61`); other outcomes go to `ExecutingState` or `UpdatingState` (`:70-158`).
16. **Verifying.** `VerifyingState.execute` skips to `CompletedState` when CoVe is off, no plan, or no completed step (`weebot/application/flows/states/verifying.py:65-91`); otherwise it runs the CoVe questions inside `WorkspaceIntegrityGuard.watch` and ends in `CompletedState` (`:104-227`).
17. **Completed.** `CompletedState.execute` stamps the plan COMPLETED or FAILED (`weebot/application/flows/states/completed.py:148-153`), emits that `PlanEvent` (`:174-176`), sets the session COMPLETED or FAILED, saves it and yields `DoneEvent` (`:267-272`), then spawns background jobs (`:423-449`).
18. **Persistence on every emit.** `PlanActFlow._emit` hands the event to `EventPublisher.emit` (`plan_act_flow.py:462-480`): truth binding, credential sanitization, `session.add_event`, bus publish plus domain events, then save (`weebot/application/flows/event_publisher.py:60-80`); see [session-persistence](session-persistence.md).
19. **Epilogue.** `AgentRunner` publishes each yielded event to its bus (`agent_runner.py:218-229`), takes the flow's session (`:232-235`), sets COMPLETED if `flow.is_done()` else WAITING (`:237-242`) and saves (`:244`). `_run_async` drains background tasks, closes the MCP toolkit and the DB pools (`cli/commands/flow.py:57-74`).

Consequences (read from source, not run):
- A session that ends FAILED never leaves the loop: `CompletedState` sets no next state and keeps `AgentStatus.COMPLETED` (`completed.py:136, 480-482`), and the loop breaks only on COMPLETED/WAITING or IDLE (`plan_act_flow.py:802-807`), so `CompletedState` re-runs until `max_iterations`. `AgentRunner` then overwrites FAILED with WAITING (`agent_runner.py:237-242`). The same overwrite hits a cancelled turn (`plan_act_flow.py:700-704`).
- A termination condition sets `CompletedState` and returns before it runs (`plan_act_flow.py:734-735`): no terminal status, no `DoneEvent`.
- Events are published twice when the runner has a bus: once in `EventPublisher.emit` (`event_publisher.py:74-76`), once by `AgentRunner` for the yielded copy (`agent_runner.py:227-228`). `flow run` now passes the bus (`cli/commands/flow.py:124`).
- `--model` reaches the planner command and the step command's `model` (`planning.py:204`, `executing.py:459`), but the executor's cascade never reads `ExecutorAgent._model` (`_base.py:249`; cascade inputs `_cascade.py:446-485`), so it does not pick the step's model.
- The step handler reads the plan from the database (`execute_step_handler.py:72-78`), not from the flow. An edited plan file applied by `_apply_plan_file` lives only in memory (`flow_router.py:25-42`) until the next emit; no emit runs before `ExecuteStepCommand` (`executing.py:293-465`), so an edited step id `edited-N` is not found (`execute_step_handler.py:84-88`).

## If you change this
**Hits:** `cli/commands/flow.py` run/resume, `AgentRunner`, `create_flow` / `build_tools`, every state's `set_state` target, `ExecuteStepHandler`, `EventPublisher`; tests `tests/unit/cli/test_flow_run_without_stdin.py`, `tests/unit/cli/test_flow_one_container.py`, `tests/unit/fixes/test_create_flow_persistence.py`, `tests/unit/fixes/test_per_step_tool_scope.py`, `tests/e2e/test_flow_e2e.py`.
**Does not hit:** the web `TaskRunner` path (`weebot/application/services/task_runner.py`), which starts flows through the DI `create_flow` service, not `AgentRunner`; `ChatFlow`.

## See
`cli/commands/flow.py`, `weebot/interfaces/cli/agent_runner.py`, `weebot/application/flows/plan_act_flow.py`, `weebot/application/flows/states/`
