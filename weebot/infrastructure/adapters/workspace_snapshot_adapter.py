"""LocalWorkspaceSnapshotAdapter — filesystem implementation of WorkspaceSnapshotPort.

LongHorizon-Harness E7b. Detects writes to the workspace across an episode.

Strategy — enumerate with git, compare with stat:

  * File list comes from ``git ls-files --cached --others --exclude-standard``
    when the workspace is a repository. This is the cheap way to get
    "files that matter": it already excludes .git/, node_modules/, build
    output, and everything else .gitignore covers. WORKSPACE_ROOT defaults
    to the process cwd (config.settings), which for weebot is the whole
    repo — walking it blindly would be far more expensive than the check
    is worth.
  * Change detection is (size, mtime_ns) per file, not content hashing.
    Hashing thousands of files on every verification episode costs more
    than the signal is worth here.

``git status --porcelain`` is deliberately NOT the comparison mechanism:
it reports dirtiness relative to HEAD, so a file that was already modified
before the episode shows the identical `` M path`` line after being modified
again. It cannot see the write this guard exists to catch.

Known blind spot: a write that restores both size and mtime_ns is invisible.
That requires deliberate mtime forgery, which is not the failure mode this
guards against (an agent tool writing a file it should not have).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from weebot.application.ports.workspace_snapshot_port import (
    WorkspaceDrift,
    WorkspaceSnapshot,
    WorkspaceSnapshotPort,
)

_log = logging.getLogger(__name__)

_BACKEND = "local-stat-manifest"

# Directories never worth scanning when git cannot supply the file list.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".turbo",
        "htmlcov",
        ".tox",
    }
)

_DEFAULT_MAX_FILES = 20_000
_DEFAULT_GIT_TIMEOUT = 10.0


class LocalWorkspaceSnapshotAdapter(WorkspaceSnapshotPort):
    """Snapshots the local workspace as a bounded (size, mtime) manifest.

    Args:
        root_dir: Workspace root to scan. Defaults to config WORKSPACE_ROOT.
        max_files: Hard cap on manifest size. Past it the snapshot is marked
            truncated rather than growing without bound.
        git_timeout: Seconds to wait for ``git ls-files`` before falling
            back to a filesystem walk.
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        max_files: int = _DEFAULT_MAX_FILES,
        git_timeout: float = _DEFAULT_GIT_TIMEOUT,
    ) -> None:
        if root_dir is None:
            from weebot.config.settings import WORKSPACE_ROOT

            root_dir = WORKSPACE_ROOT
        self._root = Path(root_dir).resolve()
        self._max_files = max_files
        self._git_timeout = git_timeout

    # ── Port surface ────────────────────────────────────────────────

    async def snapshot(self) -> WorkspaceSnapshot:
        """Capture a manifest. Never raises — see the port contract."""
        try:
            manifest, truncated = await self._build_manifest()
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("Workspace snapshot failed", exc_info=True)
            return WorkspaceSnapshot(
                backend=_BACKEND, payload={"error": f"{type(exc).__name__}: {exc}"}
            )
        return WorkspaceSnapshot(
            backend=_BACKEND, payload={"files": manifest, "truncated": truncated}
        )

    async def diff(self, before: WorkspaceSnapshot) -> WorkspaceDrift:
        """Compare now against *before*, failing closed if either end is unusable."""
        if before.backend != _BACKEND:
            return WorkspaceDrift(
                unavailable_reason=f"snapshot from foreign backend {before.backend!r}"
            )

        payload = before.payload if isinstance(before.payload, dict) else {}
        if "error" in payload:
            return WorkspaceDrift(unavailable_reason=f"baseline unavailable: {payload['error']}")
        if "files" not in payload:
            return WorkspaceDrift(unavailable_reason="baseline snapshot is malformed")

        after = await self.snapshot()
        after_payload = after.payload if isinstance(after.payload, dict) else {}
        if "files" not in after_payload:
            reason = after_payload.get("error", "comparison snapshot is malformed")
            return WorkspaceDrift(unavailable_reason=f"could not re-scan workspace: {reason}")

        old: dict[str, tuple[int, int]] = payload["files"]
        new: dict[str, tuple[int, int]] = after_payload["files"]

        added = tuple(sorted(new.keys() - old.keys()))
        removed = tuple(sorted(old.keys() - new.keys()))
        modified = tuple(sorted(p for p in (old.keys() & new.keys()) if old[p] != new[p]))

        return WorkspaceDrift(
            added=added,
            modified=modified,
            removed=removed,
            # Either end being truncated means the listing is a sample: a
            # capped scan can report a spurious add/remove purely from where
            # the cap fell, so the result is indicative, not exhaustive.
            truncated=bool(payload.get("truncated") or after_payload.get("truncated")),
        )

    # ── Manifest construction ───────────────────────────────────────

    async def _build_manifest(self) -> tuple[dict[str, tuple[int, int]], bool]:
        if not self._root.is_dir():
            raise FileNotFoundError(f"workspace root does not exist: {self._root}")

        paths = await self._git_file_list()
        if paths is None:
            paths, truncated = self._walk_file_list()
        else:
            # git already honours .gitignore, but only where one exists —
            # a workspace nested inside someone else's repo (or one with no
            # ignore rules) gets node_modules/ listed in full. Prune the
            # same set in both branches so the two agree.
            paths = [p for p in paths if not self._is_skipped(p)]
            truncated = len(paths) > self._max_files
            paths = paths[: self._max_files]

        return await asyncio.to_thread(self._stat_all, paths), truncated

    @staticmethod
    def _is_skipped(rel: str) -> bool:
        """True if any *directory* component is a skip dir.

        The final component is excluded so a file legitimately named
        ``build`` or ``dist`` is not dropped.
        """
        parts = rel.replace("\\", "/").split("/")
        return any(part in _SKIP_DIRS for part in parts[:-1])

    def _stat_all(self, paths: list[str]) -> dict[str, tuple[int, int]]:
        """Stat every path off the event loop — thousands of syscalls."""
        manifest: dict[str, tuple[int, int]] = {}
        for rel in paths:
            try:
                st = (self._root / rel).stat()
            except OSError:
                continue  # vanished or unreadable between listing and stat
            manifest[rel] = (st.st_size, st.st_mtime_ns)
        return manifest

    async def _git_file_list(self) -> list[str] | None:
        """Tracked + untracked-but-not-ignored files. None if git is unusable."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                cwd=str(self._root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception:
            # Deliberately broad: this is the "git didn't work" branch, and
            # the walk fallback handles every reason equally. Notably
            # NotImplementedError — asyncio refuses to spawn subprocesses on
            # a SelectorEventLoop (Windows), which is not an error worth
            # failing an integrity check over.
            _log.debug("git unavailable for workspace listing", exc_info=True)
            return None

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._git_timeout)
        except TimeoutError:
            _log.debug("git ls-files timed out after %ss — falling back to walk", self._git_timeout)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return None

        if proc.returncode != 0:
            return None  # not a repository, or git refused

        # -z output is NUL-separated, so paths with spaces or newlines survive.
        return [p for p in stdout.decode("utf-8", errors="replace").split("\0") if p]

    def _walk_file_list(self) -> tuple[list[str], bool]:
        """Fallback for non-git workspaces: bounded walk, heavy dirs pruned."""
        paths: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for name in filenames:
                full = Path(dirpath) / name
                try:
                    paths.append(str(full.relative_to(self._root)))
                except ValueError:
                    continue
                if len(paths) >= self._max_files:
                    return paths, True
        return paths, False
