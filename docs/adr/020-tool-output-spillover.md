# ADR-020: Tool output past the cap spills to a file instead of being discarded

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H7, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Start h7".
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`ToolCollection.execute` cut any output over `MAX_TOOL_OUTPUT_CHARS` (20 000) and dropped the rest. A build log or a large file listing lost the line the model needed, with no way to get it back. Nothing bounded the sum of one turn's outputs either: five parallel calls could each return 20 000 characters.

## Decision

1. **A new port, `SpilloverStorePort`** (`weebot/application/ports/spillover_store_port.py`): `write(session_id, call_id, text) -> SpillRef`, `purge(session_id)`. `FileSpilloverStore` writes `<base>/<session>/<call>.txt` under `~/.weebot/spillover`, through `asyncio.to_thread`. Ids are made path-safe, and distinct ids stay distinct.
2. **The truncation point keeps the original.** `ToolCollection.execute` still truncates, and also leaves the full text in `metadata["full_output"]`. The key is transient: `ToolExecutor.execute_tool` pops it on every path, so it never reaches events or persistence.
3. **Spilling is middleware.** `SpilloverMiddleware.transform_tool_result` (an H16 hook) stores the text and replaces the output with a 60% head, 40% tail preview that fits the 20 000-character cap and ends with `[full output: <path>, N chars — read with file_editor view view_range=[a,b]]`. An `.error` over 8 000 characters gets the same treatment.
4. **A per-turn budget.** `ToolBatchRunner.run` sums the batch's outputs in order. Once the sum passes `WEEBOT_TURN_OUTPUT_BUDGET` (default 60 000), each later result shrinks to a 2 000-character preview, spilling first if it had not already.
5. **D5: reading a spill file taints the session.** The system writes spill files, so they are never passed to `note_written_file`. A `file_editor view` of one is therefore new content, as the original output was. A test fails if spill paths are ever added to the written-file exemption.
6. **Wiring.** The port is bound in `_capabilities.py`. `Container.step_executor` passes the store and a `MiddlewareChain([SpilloverMiddleware])` (`_spillover_kwargs`). A session delete purges the directory (`_session_stores`).

## Consequences

- The model can read the whole output, in ranges, at the cost of one more tool call.
- The first production `MiddlewareChain`. A flow that supplies its own `middleware_chain` in its step context replaces this one, and so loses spilling; the executor still truncates and drops the transient copy.
- Spill files live under `~/.weebot/spillover`, not the plan's `data/` (a tracked directory), and are removed only with their session.
- The per-turn budget counts characters, not tokens.
- The budget runs over a batch, so a turn that makes several one-call batches is not bounded by it.
