---
type: object
name: LoopDetectors
code: GuardConfig, CycleDetector, DuplicateResultStub, EmptyResponseBudget, RepetitionGuard, WallClockWrapUp, IterationGuard
cluster: application
universe: live
status: stub
---

# LoopDetectors

The checks that notice an executor step going in circles, and the one config that holds their numbers.

## Why this shape
Each check watches something different and keeps its own state, so each is a small class with a typed `observe`; `IterationGuard` composes them. ADR-021 has the reasoning.

## Shape
- `GuardConfig` is the only place the limits live (`weebot/application/agents/executor/_loop_detectors.py`).
- `CycleDetector`, `DuplicateResultStub`, `EmptyResponseBudget`, `RepetitionGuard` and `WallClockWrapUp` return a `GuardVerdict`, a stub string or a note, and never raise (same file).
- `IterationGuard` owns the step's counters and four of the detectors; `record_tool_call` returns the cycle verdict (`weebot/application/agents/executor/_iteration_guard.py`).

## Connected to
`ExecutorAgent.execute_step` builds the guard and the batch runner from `guard_config`, injects the wrap-up note and passes repetition notes to the batch (`weebot/application/agents/executor/_base.py`). `ToolBatchRunner` owns the stub detector and turns a cycle verdict into a hint or an abort (`weebot/application/agents/executor/_tool_batch.py`). `retry_empty_turn` applies the empty-reply budget using the cost meter's spend (`weebot/application/agents/executor/_turn.py`). Looks like but is not `TrajectoryMonitor` (cross-step health from tool output) or `MiddlewareChain` (interceptors).

## If you change this
**Hits:** when a step stops, what the model sees for a repeated result, the user-role messages in a step's buffer.
**Does not hit:** the per-step tool-call cap, the trajectory monitor, tool execution itself.

## Surfaces
Every executor step.

## See
`docs/adr/021-loop-guardrails-v2.md`
