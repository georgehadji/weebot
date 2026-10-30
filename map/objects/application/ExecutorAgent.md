---
type: object
name: ExecutorAgent
code: ExecutorAgent
cluster: application
universe: live
status: verified
verified: 2026-10-30
commit: a3d9fe16
---

# ExecutorAgent

Runs one plan step: builds a system prompt, loops "ask the model, run the tool calls it returns" until the step produces an answer, calls `terminate`, hits a guard, pauses for a human, or runs out of budget. `execute_step` is an async generator of `AgentEvent`s and ends with a `StepEvent` of COMPLETED or FAILED, or returns early after a `WaitForUserEvent`.

## Why this shape
Split from a 1,400-line class into collaborators (ADR-007 in `ARCHITECTURE.md`); the model-call logic is `CascadeExecutor`, tool dispatch is `ToolExecutor`, compaction and token counts are `ContextCompressor`, loop limits are `IterationGuard` (`weebot/application/agents/executor/_base.py:151-201, 550-555`); what the loop does with one tool result is in `_step_result_handler.py` (CPL-1). `_base.py` is still 1,225 lines. Each `execute_step` call starts clean: facts, terminate flag and conversation buffer are cleared first (`:601-603`). The container injects `injection_scan`, `effect_ledger`, `cost_meter` and `memory_snapshot` (`:246-254`), so the executor imports no tool.

## Shape
`execute_step(plan, step, user_input, session_id)` at `_base.py:449`:
1. Pass the step and session to `ToolExecutor` (approval scope and audit read it there) (`:623`), then emit `StepEvent(STARTED)` (`:625`). Build the system prompt with `build_executor_prompt`, scoped by `step.context_scope` (`:657-670`); the cached user profile is added only for `full`/`creative` scope (`:675-676`). Append `OUTPUT_ROOT` instructions and the persistent-memory snapshot from the injected callable (`:679-693`).
2. Seed the conversation buffer with goal, step position, last three completed steps and the current step, plus `user_input` on a resume (`:695-727`).
3. Loop `while self._step_budget.consume()` (`:750`). Per pass: stop with a summary call if the tool-call budget is exhausted (`:752-783`); compress context (`:785`); append session constraints as the last message, never into the evictable buffer (`:795-796`); middleware `before_request` (`:798-806`); `self._cascade.call_with_cascade` (`:810-812`).
4. `LLMCapacityExhaustedError` and `AllModelsTrippedError` yield an ErrorEvent plus a user-facing message and end the loop (`:813-840`).
5. No tool calls: the content is the step result; repeated assistant-only turns raise a loop error (`:868-885`). Tool calls: each is checked for a repeated signature and emitted as CALLING (`:890-913`), then run in parallel by `ToolExecutor.execute_tool_batch` (`:919`).
6. Per result, in order: `TrajectoryMonitor` diagnoses cross-step stalls, with at most 2 semantic-loop recoveries (`:742, 937-1011`); a repeated policy-error class yields `WaitForUserEvent` and aborts (`:1013-1053`); middleware `after_tool_call` (`:1058-1069`); `CALLED` ToolEvent (`:1071-1078`); `pause_events` (`_step_result_handler.py:15-40`) turns `awaiting_human` into `WaitForUserEvent`, and an `approval_required` result (ADR-013) into `ToolApprovalEvent` then `WaitForUserEvent`, and the step returns (`:1080-1086`); the `terminate` tool sets `_should_terminate` and ends the step (`:1088-1095`); `_present_tool_output` fences the output unless the tool's `OutputTrust` is LOCAL, errors included, and scans it for injection (`:396-417`, `weebot/core/trust_boundary.py`) (`:1097-1100`); `feed_vision` can switch the next call to a vision model (`_step_result_handler.py:43-60`; `:1102`).
7. `_handle_step_completion` (`:1129-1173`) turns a spent budget with no result, or all-tool-calls-failed with no output, into a stuck error and a FAILED StepEvent; otherwise COMPLETED.

Model choice per call: `_resolve_model_for_step` (`:476-491`) returns `MODEL_VISION_PRIMARY` if `_needs_vision`, else `_model_for_step`: `AdaptiveCapabilityRouter` when `WEEBOT_ENABLE_ACR`, else `task_model_router.model_for_step`, falling back to `MODEL_CASCADE_TIER1` (`:493-518`).

## Connected to
- **Owns:** `CascadeExecutor` (see its card), `ToolExecutor`, `ContextCompressor`, `IterationGuard`, `TrajectoryMonitor` (`:276-287`), `StepBudget` (`:299`). Outbound-action ledger and session taint live in `ToolExecutor` (see EgressGuard); the soft cost limit lives in `CascadeExecutor`.
- **Invoked through the Mediator, not directly:** `ExecutingState` sends `ExecuteStepCommand` with the flow's `step_execution_context()` (`weebot/application/flows/states/_step_run.py:56-96`) and adds the reported token usage back to the flow (`record_step_usage`, `:480`). `ExecuteStepHandler` builds the executor from the container's executor factory, else `ExecutorAgent(...)`, and iterates `execute_step` (`weebot/application/cqrs/handlers/execute_step_handler.py:102-116, 140`). The factory is `Container.step_executor`, which overlays the flow's settings (tools, skill prompt, role, learner, harness block, middleware, trajectory config, pinned model) on container singletons (ADR-015, F25; see the DI Container card). `SummarizeHandler` builds a bare one (`weebot/application/cqrs/handlers/summarize_handler.py:45`).
- **Also built by:** `PlanActFlow.__init__` as `self._summary_executor` (`weebot/application/flows/_plan_act_wiring.py:269`), used for summarizing, tool assembly and the per-step harness re-resolve; it does not run steps.
- **Looks like but is not:** `PlannerAgent` (writes plans, no tools); persona agents in `weebot/agents/`.

## If you change this
**Hits:** `ExecuteStepHandler`, `SummarizeHandler`, `Container.step_executor`, `PlanActFlow` (summary executor, token usage), `ExecutingState` (reads facts and events); the event stream consumers (CLI, WebSocket); `IterationGuard` limits (12 tool calls per step, 2 repeated assistant turns, 4 repeated tool signatures, `:729-734`); the 19 test files that reference `ExecutorAgent` (grep 2026-10-24).
**Does not hit:** plan creation (`PlannerAgent`); `FlowRouter`; model fallback order (that is `CascadeExecutor`).

## Surfaces
Events reach CLI, web and MCP via the flow's event emission. `terminate` and `ask_human`-style tools are the agent's own exits.

## See
`weebot/application/agents/executor/_base.py`
