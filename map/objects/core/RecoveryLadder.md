---
type: object
name: RecoveryLadder
code: plan_recovery, LADDERS, RecoverableLLMError, call_with_recovery
cluster: core
universe: live
status: stub
---

# RecoveryLadder

What to do after every model in the cascade failed for a reason the executor can fix: compress, strip images, wait, or tell the user precisely why not.

## Why this shape
Retrying the same overflowing payload cannot succeed, so the policy is a pure table (`weebot/core/recovery_ladder.py:46-65`) and the effects live in the executor, which owns the conversation buffer (`weebot/application/agents/executor/_recovery.py`). ADR-017 has the reasoning.

## Shape
- `LADDERS`: `ErrorCategory` to a tuple of `Rung(action, aggressive)`; `plan_recovery` returns the first rung not yet used (`weebot/core/recovery_ladder.py`).
- `terminal_error` turns the cascade's per-model error texts into a `RecoverableLLMError` with a category and `retry_after` (`weebot/application/agents/executor/_recovery.py`).
- `call_with_recovery` loops: cascade, catch, plan, perform, rebuild messages, retry (`weebot/application/agents/executor/_recovery.py`).
- `ContextCompressor.force_compress` ignores the 0.75 trigger (`weebot/application/agents/executor/_context_compressor.py`).

## Connected to
Reads `ErrorClassifier` categories (`weebot/core/error_classifier.py`). Raised from `CascadeExecutor.call_with_cascade`; called from `next_turn` (`weebot/application/agents/executor/_turn.py`). Looks like but is not the adapter's retry, which only repeats the same request.

## If you change this
**Hits:** `next_turn`, the user-facing failure text, `ResilientLLMAdapter` retry decisions (through `is_retryable`).
**Does not hit:** the circuit breakers, the per-model cascade order, `ExecutingState`'s replan skip (it matches the old tripped text only).

## Surfaces
Every executor step; the chat error message.

## See
`docs/adr/017-recovery-ladder.md`
