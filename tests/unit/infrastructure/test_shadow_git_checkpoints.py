"""Workspace checkpoints put files back, never touch the user's .git, and respect the caps (H5)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from weebot.infrastructure.checkpoints.shadow_git import ShadowGitCheckpointAdapter

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH"),
]


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("one", encoding="utf-8")
    (root / ".gitignore").write_text("secret.env\n", encoding="utf-8")
    (root / "secret.env").write_text("KEY=1", encoding="utf-8")
    return root


@pytest.fixture
def cp(tmp_path):
    return ShadowGitCheckpointAdapter(tmp_path / "checkpoints")


async def _snap(cp, ws, turn, session="s1"):
    return await cp.snapshot(session_id=session, turn_id=turn, root=ws, reason="file_editor")


async def test_rollback_restores_an_edited_file_and_removes_a_new_one(cp, ws):
    first = await _snap(cp, ws, "t1")
    assert first is not None and first.file_count >= 1
    (ws / "a.txt").write_text("two", encoding="utf-8")
    (ws / "new.txt").write_text("fresh", encoding="utf-8")

    report = await cp.restore(first)

    assert (ws / "a.txt").read_text(encoding="utf-8") == "one"
    assert not (ws / "new.txt").exists()
    assert report.restored == ("a.txt",) and report.removed == ("new.txt",)


async def test_gitignored_files_are_never_touched(cp, ws):
    first = await _snap(cp, ws, "t1")
    (ws / "secret.env").write_text("KEY=changed", encoding="utf-8")
    (ws / "a.txt").write_text("two", encoding="utf-8")
    await cp.restore(first)
    assert (ws / "secret.env").read_text(encoding="utf-8") == "KEY=changed"


async def test_a_rollback_can_itself_be_rolled_back(cp, ws):
    first = await _snap(cp, ws, "t1")
    (ws / "a.txt").write_text("two", encoding="utf-8")
    report = await cp.restore(first)
    assert (ws / "a.txt").read_text(encoding="utf-8") == "one"

    await cp.restore(report.undo_ref)
    assert (ws / "a.txt").read_text(encoding="utf-8") == "two"


async def test_one_checkpoint_per_turn_and_none_when_nothing_changed(cp, ws):
    assert await _snap(cp, ws, "t1") is not None
    (ws / "a.txt").write_text("two", encoding="utf-8")
    assert await _snap(cp, ws, "t1") is None  # same turn
    assert await _snap(cp, ws, "t2") is not None
    assert await _snap(cp, ws, "t3") is None  # unchanged since t2
    assert [r.turn_id for r in await cp.list("s1")] == ["t2", "t1"]


async def test_the_users_own_git_dir_is_untouched(cp, ws):
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    head = (ws / ".git" / "HEAD").read_bytes()
    before = sorted(p.name for p in (ws / ".git").iterdir())
    await _snap(cp, ws, "t1")
    (ws / "a.txt").write_text("two", encoding="utf-8")
    await cp.restore((await cp.list("s1"))[0])
    assert (ws / ".git" / "HEAD").read_bytes() == head
    assert sorted(p.name for p in (ws / ".git").iterdir()) == before


async def test_a_workspace_over_the_file_cap_is_skipped_with_one_warning(tmp_path, ws, caplog):
    small = ShadowGitCheckpointAdapter(tmp_path / "cp2", max_files=2)
    for i in range(5):
        (ws / f"f{i}.txt").write_text("x", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert await _snap(small, ws, "t1") is None
        assert await _snap(small, ws, "t2") is None
    assert sum("file checkpoints skipped" in r.message for r in caplog.records) == 1


async def test_diff_shows_the_change_and_paths_narrow_it(cp, ws):
    first = await _snap(cp, ws, "t1")
    (ws / "a.txt").write_text("two", encoding="utf-8")
    (ws / "b.txt").write_text("bee", encoding="utf-8")
    full = await cp.diff(first)
    assert "a.txt" in full and "b.txt" in full
    only = await cp.diff(first, paths=["b.txt"])
    assert "b.txt" in only and "a.txt" not in only


async def test_paths_restore_only_what_was_asked(cp, ws):
    (ws / "b.txt").write_text("b1", encoding="utf-8")
    first = await _snap(cp, ws, "t1")
    (ws / "a.txt").write_text("two", encoding="utf-8")
    (ws / "b.txt").write_text("b2", encoding="utf-8")
    await cp.restore(first, paths=["b.txt"])
    assert (ws / "b.txt").read_text(encoding="utf-8") == "b1"
    assert (ws / "a.txt").read_text(encoding="utf-8") == "two"


async def test_sessions_are_independent_and_deletable(cp, ws):
    await _snap(cp, ws, "t1", session="s1")
    (ws / "a.txt").write_text("two", encoding="utf-8")
    await _snap(cp, ws, "t1", session="s2")
    assert await cp.delete_session("s1") == 1
    assert await cp.list("s1") == [] and len(await cp.list("s2")) == 1


async def test_only_the_newest_n_checkpoints_are_kept(tmp_path, ws):
    cp = ShadowGitCheckpointAdapter(tmp_path / "cp3", keep_per_session=3)
    for i in range(5):
        (ws / "a.txt").write_text(str(i), encoding="utf-8")
        await _snap(cp, ws, f"t{i}")
    assert [r.turn_id for r in await cp.list("s1")] == ["t4", "t3", "t2"]


async def test_gc_removes_checkpoints_older_than_the_cutoff(cp, ws):
    await _snap(cp, ws, "t1")
    assert await cp.gc(older_than_days=14) == 0
    assert await cp.gc(older_than_days=-1) == 1
