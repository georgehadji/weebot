# ADR-019: File changes are undoable through shadow-git workspace checkpoints

**Date:** 2026-11-03
**Status:** Implemented 2026-11-03 (plan H5, `tasks/specs/hermes_v022_parity_implementation_plan.md`), under the user's instruction "Continue with H4 (delegation policy) and H5 (shadow-git checkpoints)".
**Owner:** weebot maintainers
**Supersedes:** N/A

---

## Context

Weebot could undo a plan (in memory only) but not a file edit. `CheckpointPort` stores the plan after each step, one row per session. `WorkspaceSnapshotPort` hashes the workspace to detect drift and says "never restore". An agent that overwrote or deleted a file left the user to recover it from their own version control, if they had any.

## Decision

1. **A new port, `WorkspaceCheckpointPort`** (`weebot/application/ports/workspace_checkpoint_port.py`): `snapshot`, `list`, `diff`, `restore`, `gc`, `delete_session`. The name `CheckpointPort` was taken, and the two stores differ in what they hold.
2. **Shadow git as the engine** (`weebot/infrastructure/checkpoints/shadow_git.py`). Each workspace gets its own git directory and the real directory as the work tree, so the user's `.git` is never read or written. `add -A` (`.gitignore` respected), `write-tree`, `commit-tree`, `update-ref refs/weebot/<session>/<n>`. The commit subject is a one-line JSON record (reason, turn, file count, root, session), so the refs are the only index.
3. **Fixed-argv git.** `shell=False`, a timeout, the allowlisted child environment from H1, no system or global git config. Every port method runs the blocking work in `asyncio.to_thread`.
4. **The trigger is the executor.** `ToolExecutor.execute_tool` calls `checkpoint_before_change` (`executor/_turn_checkpoint.py`) before every call. It skips calls `tool_guards.reads_only` classifies as reads, so there is no new classification. The port keeps one checkpoint per (session, step) and none when the tree has not changed since the last one.
5. **Restore undoes itself.** `restore` snapshots first, then computes the diff from the checkpoint tree to the workspace as it is now. Files added since are removed, and changed or deleted files are checked out. Gitignored files never enter a tree, so they are never touched. `RestoreReport.undo_ref` is the pre-restore checkpoint.
6. **Caps (decision D4).** Workspaces over 20 000 files or 500 MB are skipped with one warning per session. 50 checkpoints are kept per session; `gc(older_than_days)` drops older ones.
7. **Flag and purge.** `WEEBOT_FILE_CHECKPOINTS`, default on. The port is bound whether or not the flag is on, and `_session_stores()` purges a deleted session's checkpoints.
8. **Surface.** `python -m cli.main rollback [N] --session ID [--path P] [--diff] [--list]`.

## Consequences

- The first file-changing call of a step costs one `git add -A` over the workspace. The cost is bounded by the caps and paid once per step.
- Checkpoints live under `~/.weebot/checkpoints`, not the plan's `data/checkpoints`, which is a tracked directory of the repo.
- The turn is the executor's step id. A step with several model turns gets one checkpoint, taken before its first change.
- Not done, planned for later: `RollbackWorkspaceCommand` and `ListCheckpointsQuery` on the mediator, the web endpoint `POST /api/sessions/{id}/rollback`, the UI button (H35), a doctor check for git and disk use, and a default for `--session` (the latest session).
- A bash command that changes files outside the workspace root is not covered.
