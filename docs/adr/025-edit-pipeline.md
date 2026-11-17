# ADR-025: file_editor finds fuzzy matches, refuses stale writes, and checks syntax

**Date:** 2026-11-04
**Status:** Implemented 2026-11-04 (plan H6, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Proceed to h6". The eval gate is not run (see Consequences).
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

`file_editor` offered `view`, `create`, `str_replace`, `insert` and `write_large`, and had these faults:

- `str_replace` matched `old_str` character for character, so one wrong indent, a smart quote or a doubled escape failed the edit, and the model retried in a loop.
- When `old_str` matched twice, the first match was replaced and the model was not told.
- The tool did not record what the model had seen. It overwrote a file that something else had changed since the model viewed it, or that the model never viewed.
- Nothing checked syntax after a write.

## Decision

1. **A match chain**, `application/services/patch_matching.py`: seven pure strategies in an ordered tuple (`exact`, `line_trimmed`, `whitespace_normalized`, `indentation_flexible`, `escape_normalized`, `unicode_normalized`, `block_anchor` at ratio 0.8). The first strategy that finds the text decides: one place applies the edit, several places refuse it and name their lines, and a later (fuzzier) strategy is never tried after an earlier one matched. No match gives the closest text and its line. The tool result names the strategy and the line.
2. **Re-indentation.** A line-based match (`line_trimmed`, `indentation_flexible`, `block_anchor`) moves the replacement from the indentation the model wrote to the file's. `escape_normalized` unescapes the replacement too.
3. **`exact: true`** turns the chain off and keeps the old behaviour, including replacing the first of several matches.
4. **`patch`**: a list of `{old_str, new_str}` hunks applied in order to the text in memory, then written once through `.tmp` and `replace`. One bad hunk writes nothing.
5. **`FileStateRegistry`** (`application/services/file_state.py`): `view` and every successful write record `(mtime_ns, size, sha256)`. `str_replace`, `patch`, `insert` and a `write_large` over an existing file are refused when the file was never viewed or has changed. A file that was only touched (same content) is allowed. `create` and a `write_large` to a new path are exempt. LRU of 512 paths.
6. **`SyntaxCheckPort`** with `InProcessSyntaxCheck` (`.py`, `.json`, `.ipynb`, `.toml`, `.yaml`/`.yml`). A problem is appended to the result as `Syntax warning: ...`; the write stands.
7. **Wiring.** Both bindings are in `Container` (`_capabilities.py`), so there is one registry per container. `tool_wiring` hands them to `file_editor` as collaborators. A tool built without them, as before, neither tracks views nor lints.

## Consequences

- An edit that failed on a small copying slip now succeeds, and says how it matched.
- An `old_str` that matches twice is refused. Before, the first match was changed silently.
- A model that edits without viewing is refused once and must view first. `file_ops.md` says so.
- **The registry is shared by every session in the container**, keyed by path. A view in one session lets another session write. The stamp check still stops a write over a file that changed. A per-session registry and the delete-cascade purge are not built; `purge()` exists and is not called.
- A change that keeps both size and mtime is not seen (the hash is read only when either differs).
- A fuzzy match can pick a wrong place that reads alike. The unique-span rule and the strategy name in the result are the defence; `exact: true` is the opt-out.
- A YAML file with template syntax can give a false warning. It is a warning, not a refusal.
- **Eval-gated, not run:** the plan requires the edit-failure-loop rate on coding suites to be at most 0.5 times the baseline. The `edit_heavy` suite and baseline do not exist yet, so no before and after numbers are attached.
- `step_evidence_auditor` still treats `patch` like `str_replace` (a partial edit), which is correct. The gate in `verifying.py` now counts `patch` as an unverified write.
- Language servers are H20.
