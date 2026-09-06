#!/usr/bin/env python3
"""Weebot Behavior Tracker - Full Iterance Integration

Filesystem watching, ledger management, and real-time event streaming.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from collections.abc import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


# git's index is one file per repository, and two processes staging at once
# lose the race: the loser fails with "Unable to create '.git/index.lock'".
# The watchdog observer dispatches on a single thread, but `mark_override`
# runs on the web or CLI thread and commits into the same repository, so the
# contention is real. Found by the concurrency vector: 12 parallel appends
# produced 12 ledger entries and 5 commits, and every dropped commit was
# correctly reported -- honest, but a tamper-evident record with most of its
# history missing is still not tamper-evident.
_GIT_LOCK = threading.Lock()


def _commit(paths: list[str], message: str, *, cwd: Path) -> bool:
    """Stage *paths* and commit them as one unit, serialized per process.

    The lock spans the pair, not each command: staging and committing are one
    logical operation against a shared index, and a lock around each half
    separately would still interleave them.
    """
    with _GIT_LOCK:
        if not _run_git(["add", "--", *paths], cwd=cwd):
            return False
        # Entries share one file per day, so a concurrent peer's commit may
        # already carry this text. git then exits 1 with "nothing to commit",
        # which is success for our purpose -- the entry is version-controlled --
        # and reporting it as a failure would be a false alarm in the other
        # direction. `diff --cached --quiet` exits 0 when nothing is staged.
        # This check is only sound because the lock spans it: without one, a
        # peer could stage between the add and the check.
        if _run_git(["diff", "--cached", "--quiet"], cwd=cwd):
            return True
        return _run_git(["commit", "-m", message], cwd=cwd)


def _run_git(args: list[str], *, cwd: Path) -> bool:
    """Run a git command, log failures without crashing, report success.

    Synchronous on purpose. Every caller -- `LedgerManager._ensure_repo`,
    `LedgerManager.append`, `TrustManager.mark_override` -- is a plain `def`
    reached from the watchdog observer thread, where there is no running event
    loop. This was an `async def` that none of them could await, so calling it
    only built a coroutine object: no git command ever ran, nothing raised, and
    the ledger reported commits it had not made. A helper whose only callers
    cannot await it is not asynchronous, it is unreachable.

    Returns True only if git ran and exited 0, so a caller can tell a commit
    from a failure instead of assuming one.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, agent-owned dir
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("Git not found on PATH — skipping git commit")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Git command 'git %s' timed out after 30s", " ".join(args))
        return False
    except Exception as exc:
        logger.debug("Git command 'git %s' error: %s", " ".join(args), exc)
        return False

    if proc.returncode != 0:
        logger.debug(
            "Git command 'git %s' failed (exit %d): %s",
            " ".join(args),
            proc.returncode,
            proc.stderr.decode(errors="replace")[:200],
        )
        return False
    return True


# Weebot ledger location
WEEBOT_DIR = Path.home() / ".weebot"
LEDGER_DIR = WEEBOT_DIR / "ledger"
TRUST_FILE = WEEBOT_DIR / "trust.json"
IGNORE_FILE = WEEBOT_DIR / "ignore.conf"
SELF_KNOWLEDGE_FILE = WEEBOT_DIR / "WEEBOT_SELF.md"

DEFAULT_IGNORE_PATTERNS = """\
# Weebot behavior tracker ignore patterns
.git/
*.swp
*.tmp
*.lock
*.pyc
__pycache__/
node_modules/
.vscode/
.idea/
.DS_Store
*.log
dist/
build/
*.egg-info/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
.tox/
.venv/
venv/
"""


@dataclass
class BehaviorEvent:
    """A single filesystem behavior event."""

    timestamp: str
    event_type: str  # created, modified, deleted, moved
    path: str
    session_id: str
    agent_version: str = "2.7.0"
    sanctioned: bool = False
    dest_path: str | None = None  # For moved events
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrustScore:
    """Trust score data."""

    score: float  # 0.0 to 1.0
    percentage: int  # 0 to 100
    total_actions: int
    overrides: int
    last_updated: str


class IgnorePatternManager:
    """Manages file ignore patterns."""

    def __init__(self):
        self.patterns: list[str] = []
        self._ensure_config()
        self._load_patterns()

    def _ensure_config(self):
        """Create default ignore file if not exists."""
        if not IGNORE_FILE.exists():
            WEEBOT_DIR.mkdir(parents=True, exist_ok=True)
            IGNORE_FILE.write_text(DEFAULT_IGNORE_PATTERNS)

    def _load_patterns(self):
        """Load patterns from config file."""
        self.patterns = []
        if IGNORE_FILE.exists():
            for line in IGNORE_FILE.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    self.patterns.append(line)

        # Also check environment variable
        extra = os.environ.get("WEEBOT_EXTRA_IGNORE", "")
        if extra:
            for p in extra.split(","):
                p = p.strip()
                if p:
                    self.patterns.append(p)

    def should_ignore(self, path: str) -> bool:
        """Check if path should be ignored."""
        if not path:
            return False

        # Always ignore temp files
        if ".tmp." in path:
            return True

        basename = os.path.basename(path)
        path_parts = set(Path(path).parts)

        for pattern in self.patterns:
            if pattern.endswith("/"):
                # Directory pattern
                dir_name = pattern.rstrip("/")
                if dir_name in path_parts:
                    return True
            else:
                # File pattern
                if fnmatch.fnmatch(basename, pattern):
                    return True
                if fnmatch.fnmatch(path, pattern):
                    return True

        return False


class LedgerManager:
    """Manages the git-backed action ledger."""

    def __init__(self):
        self._ensure_repo()
        self._dedup_cache: dict[str, float] = {}  # path -> last create time

    def _ensure_repo(self):
        """Initialize git repository if needed."""
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)

        git_dir = LEDGER_DIR / ".git"
        if not git_dir.exists():
            logger.info("Initializing behavior ledger git repository")
            if not _run_git(["init"], cwd=LEDGER_DIR):
                # Without a repository there is no ledger, only a pile of
                # markdown. Say so once, here, rather than letting every later
                # commit fail quietly into a debug log.
                logger.warning(
                    "Behavior ledger git repository could not be created at %s — "
                    "entries will still be written but are NOT version-controlled "
                    "and carry no immutability guarantee.",
                    LEDGER_DIR,
                )
                return
            _run_git(["config", "user.name", "Weebot Behavior Tracker"], cwd=LEDGER_DIR)
            _run_git(["config", "user.email", "weebot@localhost"], cwd=LEDGER_DIR)

            # Initial commit
            readme = LEDGER_DIR / "README.md"
            readme.write_text("# Weebot Behavior Ledger\n\nImmutable record of agent actions.\n")
            _commit(["README.md"], "Initial commit", cwd=LEDGER_DIR)

    def _format_entry(self, event: BehaviorEvent) -> str:
        """Format event as ledger entry."""
        ts = datetime.fromisoformat(event.timestamp).strftime("%Y-%m-%d %H:%M:%S")

        if event.event_type == "watcher_died":
            return f"[{ts}]\n" f"WATCHER STOPPED -- the observer exited unexpectedly"

        initiated = "by user" if event.sanctioned else "autonomous"

        entry = (
            f"[{ts}]\n"
            f"ACTION     {event.event_type} {event.path}\n"
            f"INITIATED  {initiated}\n"
            f"OUTCOME    observed"
        )

        if event.dest_path:
            entry += f"\nDEST       {event.dest_path}"

        # Add session metadata as HTML comment
        entry += f"\n<!-- session:{event.session_id} agent:{event.agent_version} -->"

        return entry

    def _deduplicate(self, event: BehaviorEvent) -> bool:
        """Check if event is a duplicate (watchdog double-fire)."""
        now = time.monotonic()

        if event.event_type == "created":
            self._dedup_cache[event.path] = now
            return False

        if event.event_type == "modified":
            create_time = self._dedup_cache.get(event.path)
            if create_time is not None and (now - create_time) < 1.0:
                return True  # Skip - likely double-fire after create

        return False

    def append(self, event: BehaviorEvent) -> bool:
        """Append event to ledger. Returns True if written."""
        # Skip directories
        if os.path.isdir(event.path):
            return False

        # Skip duplicates
        if self._deduplicate(event):
            return False

        # Format entry
        entry_text = self._format_entry(event)
        date_str = event.timestamp[:10]
        action_label = f"{event.event_type}: {Path(event.path).name}"

        # Write to file
        md_file = LEDGER_DIR / f"{date_str}.md"
        with open(md_file, "a", encoding="utf-8") as f:
            if md_file.exists() and md_file.stat().st_size > 0:
                f.write("\n")
            f.write(entry_text + "\n")

        # Git commit. The entry is on disk either way; what the commit adds is
        # the tamper-evidence, so a failure to commit must not be logged as one.
        committed = _commit([md_file.name], action_label, cwd=LEDGER_DIR)
        if committed:
            logger.debug("Ledger: committed %s", action_label)
        else:
            logger.warning(
                "Ledger: wrote %s but the git commit failed — the entry is on "
                "disk and is not version-controlled.",
                action_label,
            )
        return True


class TrustManager:
    """Manages trust scoring."""

    def __init__(self):
        self._ensure_file()

    def _ensure_file(self):
        """Ensure trust file exists."""
        WEEBOT_DIR.mkdir(parents=True, exist_ok=True)
        if not TRUST_FILE.exists():
            self._save(1.0, 0, 0)

    def _save(self, score: float, total: int, overrides: int):
        """Save trust data."""
        data = {
            "score": score,
            "total": total,
            "overrides": overrides,
            "last_updated": datetime.now(UTC).isoformat(),
        }
        TRUST_FILE.write_text(json.dumps(data, indent=2) + "\n")

    def load(self) -> TrustScore:
        """Load trust data."""
        try:
            data = json.loads(TRUST_FILE.read_text())
            total = data.get("total", 0)
            overrides = data.get("overrides", 0)
            score = data.get("score", 1.0)

            return TrustScore(
                score=score,
                percentage=int(score * 100),
                total_actions=total,
                overrides=overrides,
                last_updated=data.get("last_updated", ""),
            )
        except (json.JSONDecodeError, FileNotFoundError):
            return TrustScore(1.0, 100, 0, 0, "")

    def record_action(self):
        """Record a new action."""
        trust = self.load()
        total = trust.total_actions + 1
        score = (total - trust.overrides) / total if total > 0 else 1.0
        self._save(score, total, trust.overrides)
        return self.load()

    def mark_override(self, timestamp: str, reason: str) -> bool:
        """Mark an entry as overridden."""
        # Find and update entry in ledger
        for md_file in LEDGER_DIR.glob("*.md"):
            content = md_file.read_text()
            if timestamp in content:
                # Add override marker
                new_content = content.replace(
                    f"[{timestamp}]", f"[OVERRIDE] [{timestamp}]\nREASON     {reason}"
                )
                md_file.write_text(new_content)

                # Commit the change
                if not _commit([md_file.name], f"Override: {timestamp}", cwd=LEDGER_DIR):
                    logger.warning(
                        "Override for %s was written but the git commit failed.", timestamp
                    )

                # Update trust score
                trust = self.load()
                total = trust.total_actions
                overrides = trust.overrides + 1
                score = (total - overrides) / total if total > 0 else 0.0
                self._save(score, total, overrides)

                return True

        return False


class WatcherHandler(FileSystemEventHandler):
    """Handles filesystem events."""

    def __init__(
        self,
        session_id: str,
        ledger: LedgerManager,
        trust: TrustManager,
        ignore: IgnorePatternManager,
        event_callback: Callable[[BehaviorEvent], None] | None = None,
    ):
        self.session_id = session_id
        self.ledger = ledger
        self.trust = trust
        self.ignore = ignore
        self.event_callback = event_callback
        self.agent_version = "2.7.0"

    def _create_event(
        self, event_type: str, src_path: str, dest_path: str | None = None
    ) -> BehaviorEvent:
        """Create a behavior event."""
        return BehaviorEvent(
            timestamp=datetime.now(UTC).isoformat(),
            event_type=event_type,
            path=src_path,
            session_id=self.session_id,
            agent_version=self.agent_version,
            sanctioned=False,
            dest_path=dest_path,
        )

    def _handle_event(self, event_type: str, src_path: str, dest_path: str | None = None):
        """Process a filesystem event."""
        # Skip ignored paths
        if self.ignore.should_ignore(src_path):
            return

        event = self._create_event(event_type, src_path, dest_path)

        # Write to ledger
        if self.ledger.append(event):
            # Update trust score
            self.trust.record_action()

            # Notify callback
            if self.event_callback:
                try:
                    self.event_callback(event)
                except Exception as e:
                    logger.warning(f"Event callback failed: {e}")

    def on_created(self, event):
        self._handle_event("created", event.src_path)

    def on_modified(self, event):
        self._handle_event("modified", event.src_path)

    def on_deleted(self, event):
        self._handle_event("deleted", event.src_path)

    def on_moved(self, event):
        self._handle_event("moved", event.src_path, event.dest_path)


class BehaviorTracker:
    """Main behavior tracking manager."""

    def __init__(
        self,
        session_id: str,
        watch_dir: Path,
        event_callback: Callable[[BehaviorEvent], None] | None = None,
    ):
        self.session_id = session_id
        self.watch_dir = watch_dir
        self.event_callback = event_callback

        self.ledger = LedgerManager()
        self.trust = TrustManager()
        self.ignore = IgnorePatternManager()
        self.handler = WatcherHandler(
            session_id=session_id,
            ledger=self.ledger,
            trust=self.trust,
            ignore=self.ignore,
            event_callback=event_callback,
        )
        self.observer: Observer | None = None
        self._running = False

    def start(self):
        """Start watching."""
        if self._running:
            logger.warning("Behavior tracker already running")
            return

        logger.info(f"Starting behavior tracker for session {self.session_id}")
        logger.info(f"Watching directory: {self.watch_dir}")

        self.observer = Observer()
        self.observer.schedule(self.handler, path=str(self.watch_dir), recursive=True)
        self.observer.start()
        self._running = True

    def stop(self):
        """Stop watching."""
        if not self._running:
            return

        logger.info(f"Stopping behavior tracker for session {self.session_id}")

        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None

        self._running = False

    def is_running(self) -> bool:
        """Check if tracker is running."""
        return self._running and self.observer is not None and self.observer.is_alive()

    def get_stats(self) -> dict[str, Any]:
        """Get session statistics."""
        trust = self.trust.load()
        return {
            "session_id": self.session_id,
            "watch_dir": str(self.watch_dir),
            "running": self.is_running(),
            "trust_score": trust.percentage,
            "trust_details": {
                "score": trust.score,
                "total_actions": trust.total_actions,
                "overrides": trust.overrides,
                "last_updated": trust.last_updated,
            },
        }


# Global tracker registry for session management
_tracker_registry: dict[str, BehaviorTracker] = {}


def get_tracker(session_id: str) -> BehaviorTracker | None:
    """Get tracker for a session."""
    return _tracker_registry.get(session_id)


def create_tracker(
    session_id: str, watch_dir: Path, event_callback: Callable[[BehaviorEvent], None] | None = None
) -> BehaviorTracker:
    """Create and register a new tracker."""
    # Stop existing tracker for this session
    if session_id in _tracker_registry:
        _tracker_registry[session_id].stop()

    tracker = BehaviorTracker(session_id, watch_dir, event_callback)
    _tracker_registry[session_id] = tracker
    return tracker


def stop_tracker(session_id: str):
    """Stop and remove a tracker."""
    if session_id in _tracker_registry:
        _tracker_registry[session_id].stop()
        del _tracker_registry[session_id]


def stop_all_trackers():
    """Stop all trackers."""
    for tracker in list(_tracker_registry.values()):
        tracker.stop()
    _tracker_registry.clear()


if __name__ == "__main__":
    # Simple test
    import sys

    if len(sys.argv) < 2:
        print("Usage: behavior_tracker.py <directory> [session_id]")
        sys.exit(1)

    watch_dir = Path(sys.argv[1])
    session_id = sys.argv[2] if len(sys.argv) > 2 else f"test-{datetime.now().strftime('%H%M%S')}"

    def on_event(event: BehaviorEvent):
        print(f"[{event.event_type:10}] {event.path}")

    tracker = BehaviorTracker(session_id, watch_dir, on_event)
    tracker.start()

    print(f"Watching {watch_dir}... Press Ctrl+C to stop")
    try:
        while True:
            asyncio.run(asyncio.sleep(1))
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        tracker.stop()
        print(f"Trust score: {tracker.trust.load().percentage}%")
