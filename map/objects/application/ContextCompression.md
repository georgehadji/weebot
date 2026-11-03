---
type: object
name: ContextCompression
code: ContextCompressor, ConversationCompressor, CompressionPass, compress_messages, select_tail, TokenBudget
cluster: application
universe: live
status: stub
---

# ContextCompression

What shrinks the executor's conversation buffer when it nears the model's window.

## Why this shape
Old tool output is most of the weight and needs no model to remove, so cheap passes run first and the one model call runs last. ADR-022 has the reasoning.

## Shape
- `compress_messages` splits the buffer into head, middle and tail once, then runs the passes on the middle until the buffer is under target; `select_tail` picks the tail by tokens and never starts it on a tool result (`weebot/application/services/context_passes.py`).
- The passes are `PruneOldToolOutputs`, `DedupeResults`, `SummarizeMiddle` (the only model call) and `DeterministicFallback`; the order is the tuple `default_passes` (same file).
- `TokenBudget` holds the window-derived numbers: trigger 75% (50% from 512 000 tokens up), tail 20%, target 35% (same file).
- `ConversationCompressor.summarize` is the model call behind `SummarizeMiddle` and returns `""` on failure (`weebot/application/services/conversation_compressor.py`).

## Connected to
`ContextCompressor` owns the buffer, reads the window from the catalog for the model that last answered (`catalog_window`), and runs the pipeline from `_maybe_compress` and `force_compress` (`weebot/application/agents/executor/_context_compressor.py`). The cascade calls it after every response; `ExecutorAgent.execute_step` calls it before every turn (`weebot/application/agents/executor/_base.py`); the recovery ladder calls `force_compress` after a context-length error (`weebot/application/agents/executor/_recovery.py`). Pruned stubs keep the path H7 spilled to (see SpilloverStore). Looks like but is not `sanitize_tool_call_pairing`, which repairs a buffer after the fact and does not shrink it.

## If you change this
**Hits:** when compression fires, what the model sees in place of old tool output, the shape of the buffer after it, the summary model's cost.
**Does not hit:** the per-result cap (`MAX_TOOL_OUTPUT_CHARS`), the spill files, the system prompt.

## Surfaces
Every executor step that runs long enough to reach the trigger.

## See
`docs/adr/022-compression-pipeline.md`
