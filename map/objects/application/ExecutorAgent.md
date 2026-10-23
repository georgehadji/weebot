---
type: object
name: ExecutorAgent
code: ExecutorAgent
cluster: application
universe: live
status: verified
verified: 2026-10-21
commit: f00ea38
---

# ExecutorAgent

Runs one plan step: builds a system prompt, loops "ask the model, run the tool calls it returns" until the step produces an answer, calls `terminate`, hits a guard, or runs out of budget. `execute_step` is an async generator of `AgentEvent`s and ends with a `StepEvent` of COMPLETED or FAILED.

## Why this shape
Split from a 1,400-line class into collaborators (ADR-007 in `ARCHITECTURE.md`); the model-call logic is `CascadeExecutor`, tool dispatch is `ToolExecutor`, compaction and token counts are `ContextCompressor`, loop limits are `IterationGuard` (`weebot/application/agents/executor/_base.py:274-313, 598-603`). `_base.py` is still 1,110 lines. Each `execute_step` call starts clean: facts, terminate flag and conversation buffer are cleared first (`:477-479`).

## Shape
`execute_step(plan, step, user_input, session_id)` at `_base.py:474`:
1. Emit `StepEvent(STARTED)` (`:497`). Build the system prompt with `build_executor_prompt`, scoped by `step.context_scope` (`:524-537`); the cached user profile is added only for `full`/`creative` scope (`:542`). Append `OUTPUT_ROOT` instructions and the persistent-memory snapshot (`:546-562`).
2. Seed the conversation buffer with goal, step position, last three completed steps and the current step, plus `user_input` on a resume (`:564-596`).
3. Loop `while self._step_budget.consume()` (`:619`). Per pass: stop with a summary call if the tool-call budget is exhausted (`:621-652`); compress context (`:654`); append session constraints as the last message, never into the evictable buffer (`:664-665`); middleware `before_request` (`:668-675`); `self._cascade.call_with_cascade` (`:679`).
4. `LLMCapacityExhaustedError` and `AllModelsTrippedError` yield an ErrorEvent plus a user-facing message and end the loop (`:682-709`).
5. No tool calls → the content is the step result; repeated assistant-only turns raise a loop error (`:737-754`). Tool calls → each is checked for a repeated signature (`:765`), emitted as CALLING, then run in parallel by `ToolExecutor.execute_tool_batch` (`:788`).
6. Per result, in order: `awaiting_human` yields `WaitForUserEvent` and returns (`:957-960`); the `terminate` tool sets `_should_terminate` and ends the step (`:962-969`); output of untrusted tools is wrapped with `wrap_untrusted` (`:972-973`); screenshots can switch the next call to a vision model (`:980-989`). `TrajectoryMonitor` diagnoses cross-step stalls, with at most 2 semantic-loop recoveries (`:611, 808-880`).
7. `_handle_step_completion` (`:1016`) turns a spent budget with no result, or all-tool-calls-failed with no output, into a stuck error and a FAILED StepEvent; otherwise COMPLETED.

Model choice per step: `_resolve_model_for_step` (`:375`) returns a vision model if `_needs_vision`, else `AdaptiveCapabilityRouter` when `WEEBOT_ENABLE_ACR`, else `task_model_router.model_for_step`, falling back to `MODEL_CASCADE_TIER1` (`:392-417`).

## Connected to
- **Owns:** `CascadeExecutor` (see its card), `ToolExecutor`, `ContextCompressor`, `IterationGuard`, `TrajectoryMonitor`, `StepBudget`.
- **Invoked through the Mediator, not directly:** `ExecutingState` sends `ExecuteStepCommand` (`states/executing.py:444-448`); `execute_step_handler.py` builds the executor from `_executor_factory` or `ExecutorAgent(...)` and iterates `execute_step` (`cqrs/handlers/execute_step_handler.py:84-92, 119`). `summarize_handler.py:45` also builds one.
- **Also built by:** `PlanActFlow.__init__` as `self._executor` (`plan_act_flow.py:277`), which the flow uses for `token_usage` (`:718`) and `set_harness_block` (`:748`). That is **not** the executor that runs steps: `di/__init__.py:488-497` states the flow's executor "only serves the summarize fallback", and steps use the one built by `_executor_factory` (`di/__init__.py:472-500`), which is given only container-level singletons, not the flow's skill prompt, agent role, harness block, behavioral learner, middleware chain or trajectory config (`:462-471`). Implication, not tested: harness blocks and token counts the flow tracks may not reflect the executor that does the work.
- **Looks like but is not:** `PlannerAgent` (writes plans, no tools); persona agents in `weebot/agents/`.

## If you change this
**Hits:** `execute_step_handler`, `summarize_handler`, `PlanActFlow` (token usage, harness block), `ExecutingState` (reads facts and events); the event stream consumers (CLI, WebSocket); `IterationGuard` limits (12 tool calls per step, 2 repeated assistant turns, 4 repeated tool signatures, `:598-603`); the 12 test files that reference `ExecutorAgent`.
**Does not hit:** plan creation (`PlannerAgent`); `FlowRouter`; model fallback order (that is `CascadeExecutor`).

## Surfaces
Events reach CLI, web and MCP via the flow's event emission. `terminate` and `ask_human`-style tools are the agent's own exits.

## See
`weebot/application/agents/executor/_base.py`
