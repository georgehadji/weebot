"""`improve` — model-proposed edits to rule and contract files, applied by a human.

Behind WEEBOT_SELF_EDIT_CONFIG (off). `propose` asks the model for a revised file
(billed) and holds the patch as pending; nothing changes on disk until
`apply ID`, which is the human approval. `apply` and `revert` refuse when the file
changed in the meantime, and both are written to the meta-improvement log.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _data_dir() -> Path:
    from weebot.config.constants import DB_SESSIONS_PATH

    return Path(DB_SESSIONS_PATH).resolve().parent


def _project_root() -> Path:
    return Path.cwd()


def _require_flag() -> None:
    from weebot.config import feature_flags

    if not feature_flags.SELF_EDIT_CONFIG_ENABLED:
        raise click.ClickException("self-editing is off; set WEEBOT_SELF_EDIT_CONFIG=1 to use it")


def _store():
    from weebot.infrastructure.persistence.patch_store import FilePatchStore

    return FilePatchStore(_data_dir() / "self_improvement_patches")


def _improver():
    from weebot.application.services.self_improver import SelfImprover

    return SelfImprover(project_root=_project_root())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _log(action: str, patch) -> None:
    from weebot.infrastructure.persistence.meta_improvement_log import MetaImprovementLog

    before, after = (
        (patch.original_content, patch.new_content)
        if action == "apply"
        else (patch.new_content, patch.original_content)
    )
    await MetaImprovementLog(db_path=_data_dir() / "meta_improvement_log.db").record(
        editor="improve-cli",
        target_file=patch.target_file,
        change_summary=f"{action} patch {patch.id}",
        previous_hash=_digest(before),
        new_hash=_digest(after),
        rollback_info=patch.id,
    )


async def _load(patch_id: str):
    patch = await _store().get(patch_id)
    if patch is None:
        raise click.ClickException(f"no patch {patch_id}")
    return patch


@click.group()
def improve() -> None:
    """Model-proposed edits to rule and contract files (WEEBOT_SELF_EDIT_CONFIG)."""


@improve.command("propose")
@click.argument("target_file")
@click.option("--goal", default="", help="What the edit should achieve")
def improve_propose(target_file: str, goal: str) -> None:
    """Ask the model to revise TARGET_FILE from recent failures; hold it as pending."""
    _require_flag()
    from weebot.application.ports.llm_port import LLMPort
    from weebot.application.services.self_improvement_proposer import SelfImprovementProposer
    from weebot.interfaces.factories import shared_container

    async def _run():
        container = shared_container()
        proposer = SelfImprovementProposer(
            llm=container.get(LLMPort),
            improver=_improver(),
            trajectory_repo=container._maybe_get_str("trajectory_repo"),
        )
        patch = await proposer.propose(target_file, goal=goal)
        if patch is None:
            raise click.ClickException("no usable proposal (see the log)")
        await _store().save(patch)
        return patch

    patch = asyncio.run(_run())
    console.print(patch.diff or "(no diff)")
    console.print(
        f"Held as pending: {patch.id} (validation {patch.validation_score:.2f}). "
        f"Apply with: improve apply {patch.id}"
    )


@improve.command("list")
def improve_list() -> None:
    """Patches and their state."""
    patches = asyncio.run(_store().list())
    table = Table(title="Self-improvement patches")
    for column in ("Id", "File", "State", "Score"):
        table.add_column(column)
    for p in patches:
        state = "reverted" if p.reverted else "applied" if p.applied else "pending"
        table.add_row(p.id[:8], p.target_file, state, f"{p.validation_score:.2f}")
    console.print(table)


@improve.command("show")
@click.argument("patch_id")
def improve_show(patch_id: str) -> None:
    """Print a patch's diff."""
    console.print(asyncio.run(_load(patch_id)).diff or "(no diff)")


@improve.command("apply")
@click.argument("patch_id")
def improve_apply(patch_id: str) -> None:
    """Write a pending patch to its file (this is the human approval)."""
    _require_flag()

    async def _run():
        patch = await _load(patch_id)
        if patch.applied and not patch.reverted:
            raise click.ClickException("already applied")
        patch.reverted = False
        if not await _improver().apply_patch(patch):
            raise click.ClickException("not applied: the file changed or the patch is invalid")
        await _store().save(patch)
        await _log("apply", patch)

    asyncio.run(_run())
    console.print(f"[green]Applied {patch_id}[/green]")


@improve.command("revert")
@click.argument("patch_id")
def improve_revert(patch_id: str) -> None:
    """Put a patched file back as it was."""
    _require_flag()

    async def _run():
        patch = await _load(patch_id)
        if not await _improver().revert_patch(patch):
            raise click.ClickException("not reverted: it was not applied, or the file changed")
        await _store().save(patch)
        await _log("revert", patch)

    asyncio.run(_run())
    console.print(f"[green]Reverted {patch_id}[/green]")
