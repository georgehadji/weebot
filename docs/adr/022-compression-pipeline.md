# ADR-022: Compression runs as a pipeline of passes, and the window comes from the model

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H9, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "delete them and proceed". The plan marks H9 eval-gated; the before and after numbers are not collected yet.
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`ContextCompressor._maybe_compress` cut a quarter of the buffer from each end, and `ConversationCompressor.compress` then cut again (3 from the head, 6 from the tail) inside what was left. Every compression called the model, even when old tool output alone filled the context. The trigger used one fixed 128 000-token window for every model. The summary went back into the buffer as a `role: system` message in the middle, which Anthropic rejects and which changes the prompt prefix. `TokenBudgetMonitor` had no production instance.

## Decision

1. **A pipeline of passes** in `application/services/context_passes.py`. The buffer is split once into head (first 3 messages, widened to include the results of any call in it), middle, and tail. Each pass takes the middle and returns a smaller one; the pipeline stops as soon as the whole buffer is under `0.35 x window`.

   | Pass | Does | Model call |
   |---|---|---|
   | `PruneOldToolOutputs` | a tool result of 200 chars or more becomes `[tool output pruned: <tool>, N chars; spill: <path>]` (the path is kept when H7 spilled it) | no |
   | `DedupeResults` | an identical earlier result becomes `[duplicate of a later result]` | no |
   | `SummarizeMiddle` | the middle becomes one summary message | yes, the only one |
   | `DeterministicFallback` | if nothing summarized it, the middle becomes a note that lists the tools used | no |

   Order is a tuple (`default_passes`), so a new step is one entry.
2. **The tail is chosen by tokens**, not message count: `select_tail` walks back until 20% of the window is spent, keeps at least the last 4 messages, and moves its start back so it never begins on a tool result.
3. **The summary is a `role: user` message**, `[Context summary — N turns compressed]`, so the system prompt prefix stays stable (H10).
4. **The window comes from the catalog**: `catalog_window(model, default)` reads `MODELS[model].context_window`. `ContextCompressor` uses the model of the last response and falls back to the configured 128 000. The trigger is 75% of the window under 512 000 tokens, 50% from there up.
5. **`ConversationCompressor` is only the model call** (`summarize`); it no longer slices. `force_compress(ratio=0.5)` compresses as if the window were `ratio` of its size, for the recovery ladder (H3).
6. **`TokenBudgetMonitor` is deleted**, with its two constants. The pipeline owns the trigger.

## Consequences

- A tool-heavy buffer (40 results of about 5K tokens) falls under target with no model call.
- A failed or empty summary no longer leaves the buffer as it was: the fallback drops the middle and says so. The earlier rule (a failed summary is a no-op) kept the context full, so the next call failed instead.
- A pass that raises is skipped and logged; the buffer is never lost to a bug in one pass.
- The plan summary and todo list are not re-injected into the summary message. The compressor has no access to the plan, and whether the head already carries it was not checked.
- `on_pre_compress` (plan section on memory hooks) is not built.
- Token counts are the existing 4-characters-per-token estimate, so the 50% and 75% triggers are approximate.
- Eval gate still open: task success must not drop by more than 1 pp, and tokens per task must fall.
