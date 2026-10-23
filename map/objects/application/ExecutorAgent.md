---
type: object
name: ExecutorAgent
code: ExecutorAgent
cluster: application
universe: live
status: verified
verified: 2026-10-24
commit: d4ffb555
---

# ExecutorAgent

Runs one plan step: builds a system prompt, loops "ask the model, run the tool calls it returns" until the step produces an answer, calls `terminate`, hits a guard, pauses for a human, or runs out of budget. `execute_step` is an async generator of `AgentEvent`s and ends with a `StepEvent` of COMPLETED or FAILED, or returns early after a `WaitForUserEvent`.

## Why this shape
Split from a 1,400-line class into collaborators (ADR-007 in `ARCHITECTURE.md`); the model-call logic is `CascadeExecutor`, tool dispatch is `ToolExecutor`, compaction and token counts are `ContextCompressor`, loop limits are `IterationGuard` (`weebot/application/agents/executor/_base.py:289-332, 656-661`). `_base.py` is still 1,180 lines. Each `execute_step` call starts clean: facts, terminate flag and conversation buffer are cleared first (`:526-528`).

## Shape
`execute_step(plan, step, user_input, session_id)` at `_base.py:523`:
1. Pass the step and session to `ToolExecutor` (approval scope and audit read it there) (`:548`), then emit `StepEvent(STARTED)` (`:550`). Build the system prompt with `build_executor_prompt`, scoped by `step.context_scope` (`:581-595`); the cached user profile is added only for `full`/`creative` scope (`:600-601`). Append `OUTPUT_ROOT` instructions and the persistent-memory snapshot (`:604-620`).
2. Seed the conversation buffer with goal, step position, last three completed steps and the current step, plus `user_input` on a resume (`:622-654`).
3. Loop `while self._step_budget.consume()` (`:677`). Per pass: stop with a summary call if the tool-call budget is exhausted (`:679-710`); compress context (`:712`); append session constraints as the last message, never into the evictable buffer (`:719-723`); middleware `before_request` (`:725-733`); `self._cascade.call_with_cascade` (`:736-739`).
4. `LLMCapacityExhaustedError` and `AllModelsTrippedError` yield an ErrorEvent plus a user-facing message and end the loop (`:740-767`).
5. No tool calls: the content is the step result; repeated assistant-only turns raise a loop error (`:795-812`). Tool calls: each is checked for a repeated signature and emitted as CALLING (`:815-840`), then run in parallel by `ToolExecutor.execute_tool_batch` (`:846`).
6. Per result, in order: a repeated policy-error class yields `WaitForUserEvent` and aborts (`:960-980`); `CALLED` ToolEvent (`:998-1005`); `awaiting_human` yields `WaitForUserEvent` and returns (`:1010-1013`); an `approval_required` result (ADR-013) yields `ToolApprovalEvent` then `WaitForUserEvent` and returns (`:1015-1030`); the `terminate` tool sets `_should_terminate` and ends the step (`:1032-1039`); output of untrusted tools is wrapped with `wrap_untrusted` (`:1041-1046`); screenshots can switch the next call to a vision model (`:1048-1059`). `TrajectoryMonitor` diagnoses cross-step stalls, with at most 2 semantic-loop recoveries (`:668-674, 864-925`).
7. `_handle_step_completion` (`:1086-1130`) turns a spent budget with no result, or all-tool-calls-failed with no output, into a stuck error and a FAILED StepEvent; otherwise COMPLETED.

Model choice per call: `_resolve_model_for_step` (`:401-416`) returns `MODEL_VISION_PRIMARY` if `_needs_vision`, else `_model_for_step`: `AdaptiveCapabilityRouter` when `WEEBOT_ENABLE_ACR`, else `task_model_router.model_for_step`, falling back to `MODEL_CASCADE_TIER1` (`:418-443`).

## Connected to
- **Owns:** `CascadeExecutor` (see its card), `ToolExecutor`, `ContextCompressor`, `IterationGuard`, `TrajectoryMonitor` (`:266-276`), `StepBudget`.
- **Invoked through the Mediator, not directly:** `ExecutingState` sends `ExecuteStepCommand` with the flow's `step_execution_context()` (`weebot/application/flows/states/executing.py:455-464`) and adds the reported token usage back to the flow (`:474`). `ExecuteStepHandler` builds the executor from the container's executor factory, else `ExecutorAgent(...)`, and iterates `execute_step` (`weebot/application/cqrs/handlers/execute_step_handler.py:97-111, 140`). The factory is `Container.step_executor`, which overlays the flow's settings (tools, skill prompt, role, learner, harness block, middleware, trajectory config, pinned model) on container singletons (ADR-015, F25; see the DI Container card). `SummarizeHandler` builds a bare one (`weebot/application/cqrs/handlers/summarize_handler.py:45`).
- **Also built by:** `PlanActFlow.__init__` as `self._summary_executor` (`weebot/application/flows/plan_act_flow.py:291`), used for summarizing, tool assembly and the per-step harness re-resolve; it does not run steps.
- **Looks like but is not:** `PlannerAgent` (writes plans, no tools); persona agents in `weebot/agents/`.

## If you change this
**Hits:** `ExecuteStepHandler`, `SummarizeHandler`, `Container.step_executor`, `PlanActFlow` (summary executor, token usage), `ExecutingState` (reads facts and events); the event stream consumers (CLI, WebSocket); `IterationGuard` limits (12 tool calls per step, 2 repeated assistant turns, 4 repeated tool signatures, `:656-661`); the 18 test files that reference `ExecutorAgent` (grep 2026-10-24).
**Does not hit:** plan creation (`PlannerAgent`); `FlowRouter`; model fallback order (that is `CascadeExecutor`).

## Surfaces
Events reach CLI, web and MCP via the flow's event emission. `terminate` and `ask_human`-style tools are the agent's own exits.

## See
`weebot/application/agents/executor/_base.py`
