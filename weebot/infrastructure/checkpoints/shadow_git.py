"""Shadow-git workspace checkpoints (H5).

Each workspace gets its own git directory under ``base_dir`` and the real directory as the work
tree, so the user's own ``.git`` is never read or written. A checkpoint is a commit of
``add -A`` (``.gitignore`` respected) pointed at by ``refs/weebot/<session>/<n>``; its subject is a
one-line JSON record of what the checkpoint is. Git runs with fixed argv, ``shell=False``, a
timeout and the allowlisted child environment (H1).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from weebot.application.ports.workspace_checkpoint_port import WorkspaceCheckpointPort
from weebot.config.secret_accessor import SecretAccessor
from weebot.core.child_env import build_child_env
from weebot.domain.models.workspace_checkpoint import CheckpointRef, RestoreReport

logger = logging.getLogger(__name__)

_MAX_DIFF_CHARS = 200_000
DEFAULT_CHECKPOINT_DIR = Path.home() / ".weebot" / "checkpoints"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "weebot",
    "GIT_AUTHOR_EMAIL": "weebot@localhost",
    "GIT_COMMITTER_NAME": "weebot",
    "GIT_COMMITTER_EMAIL": "weebot@localhost",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}
_FORMAT = "%(refname)%09%(objectname)%09%(tree)%09%(committerdate:unix)%09%(contents:subject)"


class _GitError(RuntimeError):
    pass


def _safe(session_id: str) -> str:
    """A ref-name-safe form of a session id; distinct ids stay distinct."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]|\.\.", "_", session_id).strip(".") or "s"
    if cleaned == session_id and not cleaned.endswith(".lock"):
        return cleaned
    return f"{cleaned}-{hashlib.sha1(session_id.encode()).hexdigest()[:8]}"


class ShadowGitCheckpointAdapter(WorkspaceCheckpointPort):
    def __init__(
        self,
        base_dir: Path,
        *,
        max_files: int = 20_000,
        max_bytes: int = 500 * 1024 * 1024,
        keep_per_session: int = 50,
        timeout_s: int = 60,
    ) -> None:
        self._base = Path(base_dir)
        self._git = shutil.which("git")
        self._max_files, self._max_bytes = max_files, max_bytes
        self._keep, self._timeout = keep_per_session, timeout_s
        self._lock = threading.Lock()
        self._last_turn: dict[str, str] = {}
        self._warned: set[str] = set()

    # ── git plumbing ───────────────────────────────────────────────

    def _gitdir(self, root: Path) -> Path:
        return self._base / hashlib.sha1(str(root).encode()).hexdigest()[:16]

    def _run(self, gitdir: Path, root: Path | None, *args: str, stdin: bytes | None = None) -> str:
        declared = {**_IDENTITY, "GIT_DIR": str(gitdir)}
        if root is not None:
            declared["GIT_WORK_TREE"] = str(root)
        env = build_child_env(SecretAccessor.environ_view(), declared=declared, inherit_proxy=False)
        proc = subprocess.run(  # noqa: S603 - fixed argv, shell=False
            [self._git, *args],
            cwd=root or gitdir,
            env=env,
            input=stdin,
            capture_output=True,
            timeout=self._timeout,
            shell=False,
        )
        if proc.returncode != 0:
            raise _GitError(proc.stderr.decode("utf-8", "replace").strip()[:300])
        return proc.stdout.decode("utf-8", "replace")

    def _init(self, root: Path) -> Path:
        gd = self._gitdir(root)
        if not (gd / "HEAD").exists():
            gd.mkdir(parents=True, exist_ok=True)
            self._run(gd, root, "init", "-q")
            for key, value in (
                ("core.autocrlf", "false"),
                ("gc.auto", "0"),
                ("core.quotepath", "off"),
            ):
                self._run(gd, root, "config", key, value)
        return gd

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message)

    def _over_caps(self, gd: Path, root: Path) -> tuple[int, str | None]:
        listing = self._run(gd, root, "ls-files", "-co", "--exclude-standard", "-z")
        names = [n for n in listing.split("\0") if n]
        if len(names) > self._max_files:
            return len(names), f"{len(names)} files (cap {self._max_files})"
        total = 0
        for name in names:
            try:
                total += (root / name).stat().st_size
            except OSError:
                continue  # vanished or unreadable; git add --ignore-errors skips it too
            if total > self._max_bytes:
                return len(names), f"over {self._max_bytes // (1024 * 1024)} MB"
        return len(names), None

    def _refs(self, gd: Path, session: str | None = None) -> list[CheckpointRef]:
        prefix = f"refs/weebot/{_safe(session)}/" if session else "refs/weebot/"
        out = self._run(gd, None, "for-each-ref", "--sort=-refname", f"--format={_FORMAT}", prefix)
        refs = []
        for line in out.splitlines():
            name, _sha, tree, ts, subject = line.split("\t", 4)
            try:
                meta = json.loads(subject)
            except ValueError:
                logger.debug("checkpoint %s has no JSON subject; skipped", name)
                continue
            refs.append(
                CheckpointRef(
                    id=name.removeprefix("refs/weebot/"),
                    session_id=meta.get("session", ""),
                    turn_id=meta.get("turn", ""),
                    tree_sha=tree,
                    root=meta.get("root", ""),
                    created_at=datetime.fromtimestamp(int(ts), UTC),
                    file_count=int(meta.get("files", 0)),
                    reason=meta.get("reason", ""),
                )
            )
        return refs

    def _all_gitdirs(self) -> list[Path]:
        if not self._base.is_dir():
            return []
        return [d for d in self._base.iterdir() if (d / "HEAD").exists()]

    # ── operations (sync; the port methods run them in a thread) ────

    def _snapshot(
        self, session_id: str, turn_id: str, root: Path, reason: str, *, force: bool = False
    ) -> CheckpointRef | None:
        if self._git is None:
            self._warn_once("nogit", "file checkpoints disabled: git is not on PATH")
            return None
        with self._lock:
            if not force and self._last_turn.get(session_id) == turn_id:
                return None
            self._last_turn[session_id] = turn_id
            root = root.resolve()
            gd = self._init(root)
            count, over = self._over_caps(gd, root)
            if over:
                self._warn_once(f"cap:{session_id}", f"file checkpoints skipped for {root}: {over}")
                return None
            self._run(gd, root, "add", "-A", "--ignore-errors")
            tree = self._run(gd, root, "write-tree").strip()
            existing = self._refs(gd, session_id)
            if existing and existing[0].tree_sha == tree:
                return existing[0] if force else None
            meta = {
                "reason": reason[:200],
                "turn": turn_id,
                "files": count,
                "root": str(root),
                "session": session_id,
            }
            parent: tuple[str, ...] = ()
            if existing:
                head = self._run(gd, None, "rev-parse", f"refs/weebot/{existing[0].id}").strip()
                parent = ("-p", head)
            commit = self._run(
                gd, root, "commit-tree", tree, *parent, "-m", json.dumps(meta)
            ).strip()
            n = int(existing[0].id.rsplit("/", 1)[1]) + 1 if existing else 1
            self._run(gd, None, "update-ref", f"refs/weebot/{_safe(session_id)}/{n:06d}", commit)
            for old in existing[self._keep - 1 :]:
                self._run(gd, None, "update-ref", "-d", f"refs/weebot/{old.id}")
            return self._refs(gd, session_id)[0]

    def _list(self, session_id: str, limit: int) -> list[CheckpointRef]:
        found = [r for gd in self._all_gitdirs() for r in self._refs(gd, session_id)]
        return sorted(found, key=lambda r: r.created_at, reverse=True)[:limit]

    def _diff(self, ref: CheckpointRef, paths: Sequence[str]) -> str:
        root = Path(ref.root)
        gd = self._init(root)
        self._run(gd, root, "add", "-A", "--ignore-errors")
        now = self._run(gd, root, "write-tree").strip()
        tail = ["--", *paths] if paths else []
        return self._run(gd, root, "diff-tree", "-p", "--no-color", ref.tree_sha, now, *tail)[
            :_MAX_DIFF_CHARS
        ]

    def _restore(self, ref: CheckpointRef, paths: Sequence[str]) -> RestoreReport:
        root = Path(ref.root).resolve()
        turn = f"restore-{ref.id}-{datetime.now(UTC).timestamp()}"
        undo = self._snapshot(ref.session_id, turn, root, f"before restore of {ref.id}", force=True)
        with self._lock:
            gd = self._init(root)
            self._run(gd, root, "add", "-A", "--ignore-errors")
            now = self._run(gd, root, "write-tree").strip()
            tail = ["--", *paths] if paths else []
            listing = self._run(
                gd, root, "diff-tree", "-r", "--name-status", "-z", ref.tree_sha, now, *tail
            )
            tokens = listing.split("\0")
            changes = list(zip(tokens[0::2], tokens[1::2], strict=False))
            added = [p for s, p in changes if s == "A"]
            back = [p for s, p in changes if s and s != "A"]
            removed = []
            for rel in added:
                target = (root / rel).resolve()
                if root in target.parents:
                    target.unlink(missing_ok=True)
                    removed.append(rel)
            if back:
                self._run(gd, root, "read-tree", ref.tree_sha)
                names = "\0".join(back).encode()
                self._run(gd, root, "checkout-index", "-f", "-z", "--stdin", stdin=names)
        return RestoreReport(restored=tuple(back), removed=tuple(removed), undo_ref=undo)

    def _delete_refs(self, gd: Path, refs: list[CheckpointRef]) -> int:
        for r in refs:
            self._run(gd, None, "update-ref", "-d", f"refs/weebot/{r.id}")
        return len(refs)

    def _gc(self, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        total = 0
        with self._lock:
            for gd in self._all_gitdirs():
                old = [r for r in self._refs(gd) if r.created_at < cutoff]
                if old:
                    total += self._delete_refs(gd, old)
                    self._run(gd, None, "gc", "--prune=now", "-q")
        return total

    def _delete_session(self, session_id: str) -> int:
        with self._lock:
            self._last_turn.pop(session_id, None)
            return sum(
                self._delete_refs(gd, self._refs(gd, session_id)) for gd in self._all_gitdirs()
            )

    # ── port ───────────────────────────────────────────────────────

    async def snapshot(
        self, *, session_id: str, turn_id: str, root: Path, reason: str
    ) -> CheckpointRef | None:
        try:
            return await asyncio.to_thread(self._snapshot, session_id, turn_id, root, reason)
        except (_GitError, OSError, subprocess.SubprocessError):
            logger.warning("file checkpoint failed for session %s", session_id, exc_info=True)
            return None

    async def list(self, session_id: str, limit: int = 50) -> list[CheckpointRef]:
        return await asyncio.to_thread(self._list, session_id, limit)

    async def diff(self, ref: CheckpointRef, *, paths: Sequence[str] = ()) -> str:
        return await asyncio.to_thread(self._diff, ref, paths)

    async def restore(self, ref: CheckpointRef, *, paths: Sequence[str] = ()) -> RestoreReport:
        return await asyncio.to_thread(self._restore, ref, paths)

    async def gc(self, *, older_than_days: int) -> int:
        return await asyncio.to_thread(self._gc, older_than_days)

    async def delete_session(self, session_id: str) -> int:
        return await asyncio.to_thread(self._delete_session, session_id)
