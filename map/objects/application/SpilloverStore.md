---
type: object
name: SpilloverStore
code: SpilloverStorePort, FileSpilloverStore, SpilloverMiddleware, spill_over_budget
cluster: application
universe: live
status: stub
---

# SpilloverStore

The full text of a tool output that was too long for the context, kept on disk with a path the model can read back.

## Why this shape
Truncation lost the line the model needed. A port keeps the store swappable; the spill itself is an H16 middleware, so the executor gains no special case. ADR-020 has the reasoning.

## Shape
- `SpilloverStorePort`: `write(session_id, call_id, text) -> SpillRef`, `purge(session_id)` (`weebot/application/ports/spillover_store_port.py`).
- `FileSpilloverStore`: `<base>/<session>/<call>.txt` under `~/.weebot/spillover`, path-safe ids (`weebot/infrastructure/spillover/file_store.py`).
- `SpilloverMiddleware.transform_tool_result` swaps the output for a head and tail preview that names the file; `spill_over_budget` applies the per-turn limit (`weebot/application/services/spillover.py`).

## Connected to
`ToolCollection.execute` leaves the original in `metadata["full_output"]` (`weebot/application/models/tool_collection.py`); `ToolExecutor.execute_tool` pops it (`weebot/application/agents/executor/_tool_executor.py`). `ToolBatchRunner.run` applies the budget (`weebot/application/agents/executor/_tool_batch.py`). Registered in `weebot/application/di/_capabilities.py` and handed to the executor by `Container._spillover_kwargs` (`weebot/application/di/_factories.py`). Purged on session delete through `_session_stores` (`weebot/interfaces/web/dependencies.py`). Looks like but is not `_truncate`, which only cuts, and not `WorkspaceCheckpoint`, which holds the user's files.

## If you change this
**Hits:** every tool result over the cap, the executor's step budget of context, `~/.weebot/spillover` disk use, session deletion, the taint on reading a spill file back.
**Does not hit:** the cap itself (`MAX_TOOL_OUTPUT_CHARS`), tool-side limits such as `max_tokens` in the browser tool.

## Surfaces
Every executor tool call; the environment variable `WEEBOT_TURN_OUTPUT_BUDGET`.

## See
`docs/adr/020-tool-output-spillover.md`
