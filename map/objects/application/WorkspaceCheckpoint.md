---
type: object
name: WorkspaceCheckpoint
code: WorkspaceCheckpointPort, ShadowGitCheckpointAdapter, CheckpointRef, checkpoint_before_change
cluster: application
universe: live
status: stub
---

# WorkspaceCheckpoint

An undoable copy of the workspace's files, taken before the first file-changing tool call of a step.

## Why this shape
Git plumbing in a separate git directory gives cheap, deduplicated snapshots and a restore that never touches the user's own repository. The port keeps the engine swappable. ADR-019 has the reasoning.

## Shape
- `WorkspaceCheckpointPort`: `snapshot`, `list`, `diff`, `restore`, `gc`, `delete_session` (`weebot/application/ports/workspace_checkpoint_port.py`).
- `ShadowGitCheckpointAdapter`: one git dir per workspace under `~/.weebot/checkpoints`, refs `refs/weebot/<session>/<n>`, caps 20 000 files and 500 MB, 50 kept per session (`weebot/infrastructure/checkpoints/shadow_git.py`).
- `CheckpointRef` and `RestoreReport` are frozen value objects (`weebot/domain/models/workspace_checkpoint.py`).
- `checkpoint_before_change` is the trigger; it skips `reads_only` calls and never raises (`weebot/application/agents/executor/_turn_checkpoint.py`).

## Connected to
Registered in `weebot/application/di/_capabilities.py` and handed to the executor by `Container._workspace_checkpoints` (`weebot/application/di/_factories.py`), gated by `FILE_CHECKPOINTS_ENABLED` (`weebot/config/feature_flags.py`). Purged on session delete through `_session_stores` (`weebot/interfaces/web/dependencies.py`). Used by the CLI `rollback` (`cli/commands/rollback.py`). Looks like but is not `CheckpointPort` (the plan, per session) or `WorkspaceSnapshotPort` (detects drift, never restores).

## If you change this
**Hits:** every file-changing tool call's latency, `~/.weebot/checkpoints` disk use, session deletion, `weebot rollback`.
**Does not hit:** the plan checkpoints, the workspace integrity guard, the user's own `.git`.

## Surfaces
CLI `rollback`; the flag `WEEBOT_FILE_CHECKPOINTS`.

## See
`docs/adr/019-workspace-checkpoints.md`
