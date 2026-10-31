---
type: object
name: ExecutorAgent
code: ExecutorAgent
cluster: application
universe: live
status: verified
verified: 2026-10-31
commit: 85a51bdd
---

# ExecutorAgent

Runs one plan step: builds a system prompt, loops "ask the model, run the tool calls it returns" until the step produces an answer, calls `terminate`, hits a guard, pauses for a human, or runs out of budget. `execute_step` is an async generator of `AgentEvent`s and ends with a `StepEvent` of COMPLETED or FAILED, or returns early after a `WaitForUserEvent`.

## Why this shape
Split from a 1,400-line class into collaborators (ADR-007 in `ARCHITECTURE.md`); the model-call logic is `CascadeExecutor`, tool dispatch is `ToolExecutor`, compaction and token counts are `ContextCompressor` (all built in `weebot/application/agents/executor/_base.py:155-201`), loop limits are `IterationGuard`, built per step (`_base.py:477-482`). The loop body is split again (WB-06): setup in `_step_setup.py`, one model turn in `_turn.py`, one tool batch in `_tool_batch.py`, and what the loop does with one tool result is in `_step_result_handler.py` (CPL-1). `_base.py` is 647 lines; `execute_step` is only the loop's shape. Each `execute_step` call starts clean: facts, terminate flag and conversation buffer are cleared first (`_base.py:467-469`). The container injects `injection_scan`, `effect_ledger`, `cost_meter` and `memory_snapshot` (`_base.py:99-105`), so the executor imports no tool.

## Shape
`execute_step(plan, step, user_input, session_id)` at `_base.py:456`:
1. `prime_step` passes the step and session to `ToolExecutor` (approval scope and audit read it there) (`_step_setup.py:36-59`), then `execute_step` emits `StepEvent(STARTED)` (`_base.py:473`). `build_step_prompts` builds the system prompt with `build_executor_prompt`, scoped by `step.context_scope` (`_step_setup.py:62-85`); the cached user profile is added only for `full`/`creative` scope (`_step_setup.py:91-92`). It appends `OUTPUT_ROOT` instructions and the persistent-memory snapshot from the injected callable (`_step_setup.py:95-109`).
2. Seed the conversation buffer with goal, step position, last three completed steps and the current step, plus `user_input` on a resume (`_step_setup.py:142-177`); a later step of the same executor gets one "Next step" line instead.
3. Loop `while self._step_budget.consume()` (`_base.py:495`). Per pass: stop with a summary call if the tool-call budget is exhausted (`_base.py:498-508`, `_summarize_on_budget_cap` `_base.py:582-597`); compress context (`_base.py:511`); `next_turn` (`_base.py:513`) appends session constraints as the last message, never into the evictable buffer (`_turn.py:117-118`), runs middleware `before_request` (`_turn.py:122-135`) and calls `self._cascade.call_with_cascade` (`_turn.py:54-56`).
4. `LLMCapacityExhaustedError` and `AllModelsTrippedError` yield an ErrorEvent plus a user-facing message and end the loop (`_turn.py:57-91`).
5. No tool calls: the content is the step result; a refusal fails the step (R07) and repeated assistant-only turns raise a loop error (`_base.py:525-547`). Tool calls: each is checked for a repeated signature and emitted as CALLING (`_tool_batch.py:150-183`), then run in parallel by `ToolExecutor.execute_tool_batch` (`_tool_batch.py:130`).
6. Per result, in order (`ToolBatchRunner._process_one`, `_tool_batch.py:187-247`): `TrajectoryMonitor` diagnoses cross-step stalls, with at most 2 semantic-loop recoveries (`_tool_batch.py:48, 251-322`); a repeated policy-error class yields `WaitForUserEvent` and aborts (`_tool_batch.py:324-368`); middleware `after_tool_call` (`_tool_batch.py:370-386`); `CALLED` ToolEvent (`_tool_batch.py:220`); `pause_events` (`_step_result_handler.py:16-42`) turns `awaiting_human` into `WaitForUserEvent`, and an `approval_required` result (ADR-013) into `ToolApprovalEvent` then `WaitForUserEvent`, and the step returns (`_tool_batch.py:222-228`); the `terminate` tool sets `_should_terminate` and ends the step (`_tool_batch.py:230-240`); `_present_tool_output` fences the output unless the tool's `OutputTrust` is LOCAL, errors included, and scans it for injection (`_base.py:252-273`, `weebot/core/trust_boundary.py`) (`_tool_batch.py:242`); `feed_vision` can switch the next call to a vision model (`_step_result_handler.py:45-60`; `_tool_batch.py:247`).
7. `_handle_step_completion` (`_base.py:603-647`) turns a spent budget with no result, or all-tool-calls-failed with no output, into a stuck error and a FAILED StepEvent; otherwise COMPLETED.

Model choice per call: `_resolve_model_for_step` (`_base.py:332-347`) returns `MODEL_VISION_PRIMARY` if `_needs_vision`, else `_model_for_step`: `AdaptiveCapabilityRouter` when `WEEBOT_ENABLE_ACR`, else `task_model_router.model_for_step`, falling back to `MODEL_CASCADE_TIER1` (`_base.py:349-376`).

## Connected to
- **Owns:** `CascadeExecutor` (see its card), `ToolExecutor`, `ContextCompressor`, `IterationGuard`, `TrajectoryMonitor` (`_base.py:131-141`), `StepBudget` (`_base.py:154`). Outbound-action ledger and session taint live in `ToolExecutor` (see EgressGuard); the soft cost limit lives in `CascadeExecutor`.
- **Invoked through the Mediator, not directly:** `ExecutingState` sends `ExecuteStepCommand` with the flow's `step_execution_context()` (`weebot/application/flows/states/_step_run.py:56-94`) and adds the reported token usage back to the flow (`record_step_usage`, `weebot/application/flows/states/_step_run.py:89`). `ExecuteStepHandler` builds the executor from the container's executor factory, else `ExecutorAgent(...)`, and iterates `execute_step` (`weebot/application/cqrs/handlers/execute_step_handler.py:102-116, 145`). The factory is `Container.step_executor`, which overlays the flow's settings (tools, skill prompt, role, learner, harness block, middleware, trajectory config, pinned model) on container singletons (ADR-015, F25; see the DI Container card). `SummarizeHandler` builds a bare one (`weebot/application/cqrs/handlers/summarize_handler.py:45`).
- **Also built by:** `PlanActFlow.__init__` as `self._summary_executor` (`weebot/application/flows/_plan_act_wiring.py:269`), used for summarizing, tool assembly and the per-step harness re-resolve; it does not run steps.
- **Looks like but is not:** `PlannerAgent` (writes plans, no tools); persona agents in `weebot/agents/`.

## If you change this
**Hits:** `ExecuteStepHandler`, `SummarizeHandler`, `Container.step_executor`, `PlanActFlow` (summary executor, token usage), `ExecutingState` (reads facts and events); the event stream consumers (CLI, WebSocket); `IterationGuard` limits (12 tool calls per step, 2 repeated assistant turns, 4 repeated tool signatures, `_base.py:477-482`); the 19 test files that reference `ExecutorAgent` (grep 2026-10-24).
**Does not hit:** plan creation (`PlannerAgent`); `FlowRouter`; model fallback order (that is `CascadeExecutor`).

## Surfaces
Events reach CLI, web and MCP via the flow's event emission. `terminate` and `ask_human`-style tools are the agent's own exits.

## See
`weebot/application/agents/executor/_base.py`
