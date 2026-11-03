"""``weebot rollback``: put the workspace back to a checkpoint taken before a step (H5).

    python -m cli.main rollback --session ID            # undo the latest checkpoint
    python -m cli.main rollback 3 --session ID          # go back three checkpoints
    python -m cli.main rollback --session ID --diff     # show what would change
    python -m cli.main rollback --session ID --path a.py --path docs/b.md
    python -m cli.main rollback --session ID --list
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console

console = Console()


async def _run(session: str, steps: int, paths: tuple[str, ...], show_diff: bool, list_only: bool):
    from weebot.infrastructure.checkpoints.shadow_git import (
        DEFAULT_CHECKPOINT_DIR,
        ShadowGitCheckpointAdapter,
    )

    # The adapter is a leaf over a directory; a second Container() here would only build a
    # second object graph (lint_container_construction).
    port = ShadowGitCheckpointAdapter(DEFAULT_CHECKPOINT_DIR)

    refs = await port.list(session, limit=max(steps, 50))
    if list_only:
        for i, r in enumerate(refs, 1):
            console.print(f"{i:>3}  {r.created_at:%Y-%m-%d %H:%M:%S}  {r.reason:<20} {r.id}")
        return
    if not refs:
        raise click.ClickException(f"no checkpoints for session {session!r}")
    if steps > len(refs):
        raise click.ClickException(f"only {len(refs)} checkpoint(s) exist for {session!r}")
    ref = refs[steps - 1]
    if show_diff:
        console.print(await port.diff(ref, paths=paths) or "(no changes)")
        return
    report = await port.restore(ref, paths=paths)
    console.print(
        f"Restored {len(report.restored)} file(s), removed {len(report.removed)} "
        f"to checkpoint {ref.id} ({ref.created_at:%H:%M:%S})."
    )
    if report.undo_ref is not None:
        console.print(f"Undo with: rollback 1 --session {session}")


@click.command("rollback")
@click.argument("steps", type=click.IntRange(min=1), default=1)
@click.option("--session", required=True, help="Session whose checkpoints to use.")
@click.option("--path", "paths", multiple=True, help="Restore only this path (repeatable).")
@click.option("--diff", "show_diff", is_flag=True, help="Show the changes instead of restoring.")
@click.option("--list", "list_only", is_flag=True, help="List the session's checkpoints.")
def cmd_rollback(
    steps: int, session: str, paths: tuple[str, ...], show_diff: bool, list_only: bool
) -> None:
    """Undo file changes: restore the workspace to the STEPS-th latest checkpoint."""
    asyncio.run(_run(session, steps, paths, show_diff, list_only))
