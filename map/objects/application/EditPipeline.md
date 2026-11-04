---
type: object
name: EditPipeline
code: apply_patch, FileStateRegistry, SyntaxCheckPort, InProcessSyntaxCheck
cluster: application
universe: live
status: stub
---

# EditPipeline

What stands between a model's `file_editor` edit and the file: where the edit lands, whether the model has seen the file as it is, and whether the result still parses.

## Why this shape
`str_replace` failed on small copying slips and replaced the first of several matches without saying so. The tool could not tell a stale view from a fresh one. ADR-025 has the reasoning.

## Shape
- `apply_patch(text, old, new, strategies=STRATEGIES)` tries seven pure strategies strictest first; the first that finds the text decides: one place applies, several refuse (with line numbers), none falls through (`weebot/application/services/patch_matching.py`). A line-based match re-indents the replacement.
- `FileStateRegistry`: `record(path)`, `check(path)`, `purge()`; an LRU of `(mtime_ns, size, sha256)` per path (`weebot/application/services/file_state.py`).
- `SyntaxCheckPort.check(path, text)`; `InProcessSyntaxCheck` covers `.py`, `.json`, `.ipynb`, `.toml`, `.yaml`/`.yml` (`weebot/application/ports/syntax_check_port.py`, `weebot/infrastructure/adapters/syntax_check.py`).

## Connected to
Used by `StrReplaceEditorTool` (`weebot/tools/file_editor.py`), which gets the registry and the checker from `Container.tool_wiring` (`weebot/application/di/_factories.py`); both are bound in `weebot/application/di/_capabilities.py`. The registry is one per container, not per session. Not the same as `WorkspaceCheckpoint`, which snapshots the workspace for undo.

## If you change this
**Hits:** `file_editor` arguments and results (`patch`, `exact`, the strategy named in the result), the tool schema in `tasks/quality/prompt_surface/`, the `file_ops.md` rule, gate 5 of `verifying.py`.
**Does not hit:** `create` of a new file, `bash` writes, the workspace path checks.

## Surfaces
The `file_editor` tool: commands `str_replace`, `patch`, `insert`, `write_large`, `view`.

## See
`docs/adr/025-edit-pipeline.md`
