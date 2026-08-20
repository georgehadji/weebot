"""Tests for LocalWorkspaceSnapshotAdapter (LongHorizon-Harness E7b).

The guard's whole value is that it fails closed: a drift check that could
not run must never read as "the workspace is clean". Several tests below
exist only to pin that distinction.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.ports.workspace_snapshot_port import WorkspaceDrift, WorkspaceSnapshot
from weebot.infrastructure.adapters.workspace_snapshot_adapter import LocalWorkspaceSnapshotAdapter


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "kept.txt").write_text("original", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("nested", encoding="utf-8")
    return tmp_path


def _adapter(root) -> LocalWorkspaceSnapshotAdapter:
    """Adapter under test, letting it pick its own listing branch.

    Do NOT assume this exercises the walk fallback. tmp_path can sit inside
    somebody else's git repository (a versioned home directory is enough),
    in which case ``git ls-files`` succeeds and the git branch runs instead.
    Tests that care which branch they are on must pin it — see
    ``_walk_only`` below.
    """
    return LocalWorkspaceSnapshotAdapter(root)


def _walk_only(monkeypatch, root) -> LocalWorkspaceSnapshotAdapter:
    """Adapter forced onto the filesystem-walk branch."""
    adapter = LocalWorkspaceSnapshotAdapter(root)
    monkeypatch.setattr(adapter, "_git_file_list", _none)
    return adapter


async def _none():
    return None


# ── Happy paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_untouched_workspace_reports_clean(workspace):
    adapter = _adapter(workspace)
    before = await adapter.snapshot()

    drift = await adapter.diff(before)

    assert drift.is_clean
    assert drift.describe() == "no workspace changes"


@pytest.mark.asyncio
async def test_new_file_is_detected_as_added(workspace):
    adapter = _adapter(workspace)
    before = await adapter.snapshot()

    (workspace / "sneaky.txt").write_text("written during verification", encoding="utf-8")

    drift = await adapter.diff(before)

    assert not drift.is_clean
    assert "sneaky.txt" in drift.added
    assert not drift.modified and not drift.removed


@pytest.mark.asyncio
async def test_deleted_file_is_detected_as_removed(workspace):
    adapter = _adapter(workspace)
    before = await adapter.snapshot()

    (workspace / "kept.txt").unlink()

    drift = await adapter.diff(before)

    assert not drift.is_clean
    assert "kept.txt" in drift.removed


@pytest.mark.asyncio
async def test_content_change_of_same_length_is_detected(workspace):
    """Same byte count, different bytes — size alone would miss this.

    Pins the reason the manifest carries mtime_ns and not just size.
    """
    adapter = _adapter(workspace)
    before = await adapter.snapshot()

    await asyncio.sleep(0.01)  # ensure the filesystem clock advances
    (workspace / "kept.txt").write_text("ORIGINAL", encoding="utf-8")  # 8 bytes either way

    drift = await adapter.diff(before)

    assert "kept.txt" in drift.modified


@pytest.mark.asyncio
async def test_nested_files_are_covered(workspace):
    adapter = _adapter(workspace)
    before = await adapter.snapshot()

    (workspace / "sub" / "nested.txt").write_text("changed content here", encoding="utf-8")

    drift = await adapter.diff(before)

    assert any("nested.txt" in p for p in drift.modified)


# ── Fail-closed paths ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_workspace_root_yields_unavailable_not_clean(tmp_path):
    """A workspace that cannot be scanned is UNKNOWN, never CLEAN."""
    adapter = _adapter(tmp_path / "does-not-exist")

    snap = await adapter.snapshot()
    drift = await adapter.diff(snap)

    assert not drift.is_clean
    assert drift.unavailable_reason
    assert "no workspace changes" not in drift.describe()


@pytest.mark.asyncio
async def test_snapshot_never_raises_on_a_broken_workspace(tmp_path):
    """Port contract: a broken guard must degrade, not crash verification."""
    adapter = _adapter(tmp_path / "nope")

    snap = await adapter.snapshot()  # must not raise

    assert isinstance(snap, WorkspaceSnapshot)
    assert "error" in (snap.payload or {})


@pytest.mark.asyncio
async def test_foreign_backend_snapshot_is_rejected_not_silently_compared(workspace):
    adapter = _adapter(workspace)

    drift = await adapter.diff(WorkspaceSnapshot(backend="some-other-impl", payload={"files": {}}))

    assert not drift.is_clean
    assert "foreign backend" in drift.unavailable_reason


@pytest.mark.asyncio
async def test_workspace_deleted_between_snapshot_and_diff(workspace):
    """The re-scan half can fail too — that is also UNKNOWN, not clean."""
    adapter = _adapter(workspace)
    before = await adapter.snapshot()

    for child in sorted(workspace.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    workspace.rmdir()

    drift = await adapter.diff(before)

    assert not drift.is_clean
    assert "could not re-scan" in drift.unavailable_reason


# ── Bounds ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manifest_is_capped_and_marked_truncated(tmp_path):
    for i in range(12):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    adapter = LocalWorkspaceSnapshotAdapter(tmp_path, max_files=5)

    snap = await adapter.snapshot()

    assert snap.payload["truncated"] is True
    assert len(snap.payload["files"]) <= 5


@pytest.mark.asyncio
async def test_truncation_propagates_into_the_drift(tmp_path):
    """A sampled scan must say so — otherwise 'clean' overclaims."""
    for i in range(12):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    adapter = LocalWorkspaceSnapshotAdapter(tmp_path, max_files=5)
    before = await adapter.snapshot()

    drift = await adapter.diff(before)

    assert drift.truncated is True


def _with_heavy_dirs(root):
    (root / "node_modules").mkdir()
    (root / "node_modules" / "huge.js").write_text("x", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "m.pyc").write_text("x", encoding="utf-8")
    (root / "real.py").write_text("x", encoding="utf-8")
    return root


def _assert_pruned(snap):
    files = snap.payload["files"]
    assert "real.py" in files
    assert not any("node_modules" in p or "__pycache__" in p for p in files)


@pytest.mark.asyncio
async def test_heavy_directories_are_pruned_from_the_walk(monkeypatch, tmp_path):
    snap = await _walk_only(monkeypatch, _with_heavy_dirs(tmp_path)).snapshot()

    _assert_pruned(snap)


@pytest.mark.asyncio
async def test_heavy_directories_are_pruned_from_the_git_listing(monkeypatch, tmp_path):
    """git only excludes what .gitignore covers.

    A workspace nested inside an unrelated repo has no ignore rules of its
    own, so git happily lists every node_modules file. Both branches must
    prune the same set or the manifest depends on where the repo boundary
    happens to fall.
    """
    root = _with_heavy_dirs(tmp_path)
    adapter = LocalWorkspaceSnapshotAdapter(root)

    async def _fake_git():
        return ["real.py", "node_modules/huge.js", "__pycache__/m.pyc"]

    monkeypatch.setattr(adapter, "_git_file_list", _fake_git)

    _assert_pruned(await adapter.snapshot())


@pytest.mark.asyncio
async def test_a_file_named_like_a_skip_dir_is_kept(monkeypatch, tmp_path):
    """Only directory components are pruned — a file called 'build' stays."""
    (tmp_path / "build").write_text("not a directory", encoding="utf-8")
    adapter = LocalWorkspaceSnapshotAdapter(tmp_path)

    async def _fake_git():
        return ["build"]

    monkeypatch.setattr(adapter, "_git_file_list", _fake_git)

    assert "build" in (await adapter.snapshot()).payload["files"]


# ── WorkspaceDrift semantics ─────────────────────────────────────────


def test_unavailable_drift_is_not_clean_even_with_no_paths():
    """The single most important line in this feature."""
    drift = WorkspaceDrift(unavailable_reason="git exploded")

    assert not drift.is_clean


def test_describe_summarises_counts_and_samples():
    drift = WorkspaceDrift(added=("a.txt",), modified=("b.txt", "c.txt"), removed=())

    text = drift.describe()

    assert "+1 added" in text and "~2 modified" in text and "-0 removed" in text
    assert "a.txt" in text
