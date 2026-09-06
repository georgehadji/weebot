"""The behaviour ledger's git backing, and the WebSocket broadcast behind it.

`LedgerManager` is documented as "the git-backed action ledger" and writes a
README calling itself an "Immutable record of agent actions". Every one of its
nine git calls invoked `_run_git_async(...)` without `await`, from a
synchronous method that cannot await. Creating a coroutine object runs no code
and raises nothing, so:

  * no git command has ever executed -- no repo, no commits, no immutability;
  * `logger.debug("Ledger: committed ...")` fired anyway, reporting the commit;
  * the `except Exception: logger.warning("Git commit failed")` guard around
    the calls could never fire, because there was nothing to fail.

The same shape sits one layer up in the router: `on_event` runs on the watchdog
observer thread, where `asyncio.get_event_loop()` raises, so the broadcast to
every connected WebSocket was swallowed at DEBUG and never delivered.

Both report success having done nothing, which is the failure mode this audit
keeps finding.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
import threading
from datetime import UTC, datetime

import pytest

from weebot.core import behavior_tracker as bt

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not on PATH"
)


def _event(path: str = "a.txt", event_type: str = "created") -> bt.BehaviorEvent:
    return bt.BehaviorEvent(
        timestamp=datetime.now(UTC).isoformat(),
        event_type=event_type,
        path=path,
        session_id="s1",
        agent_version="test",
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A LedgerManager rooted in tmp_path rather than ~/.weebot/ledger."""
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setattr(bt, "LEDGER_DIR", d)
    return bt.LedgerManager(), d


def _git(args: list[str], cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )


# --------------------------------------------------------------------------
# The claim
# --------------------------------------------------------------------------

def test_the_ledger_creates_a_git_repository(ledger):
    """A "git-backed" ledger must have a git repository behind it."""
    _, d = ledger
    assert (d / ".git").is_dir(), "no git repository was ever created"


def test_an_appended_event_becomes_a_commit(ledger):
    """The commit is the immutability guarantee. It must actually happen."""
    lm, d = ledger
    assert lm.append(_event("secrets.txt")) is True
    log = _git(["log", "--oneline"], d)
    assert log.returncode == 0, log.stderr
    assert "created: secrets.txt" in log.stdout, f"no commit for the event: {log.stdout!r}"


def test_the_committed_content_is_the_content_on_disk(ledger):
    """A commit of the wrong tree is no guarantee at all."""
    lm, d = ledger
    lm.append(_event("a.txt"))
    status = _git(["status", "--porcelain"], d)
    # Check the exit code first. Without a repo `git status` fails and prints
    # nothing, and an emptiness assertion alone would pass vacuously -- the
    # test would report clean for exactly the reason it exists to catch.
    assert status.returncode == 0, f"not a git repository: {status.stderr.strip()!r}"
    assert status.stdout.strip() == "", f"working tree not clean after append: {status.stdout!r}"


def test_an_override_is_committed(ledger):
    """`mark_override` amends the record; that amendment must be committed too."""
    lm, d = ledger
    ev = _event("b.txt")
    lm.append(ev)
    # `mark_override` matches the timestamp as the ledger *writes* it -- the
    # "YYYY-MM-DD HH:MM:SS" header form, which is also what the reporter parses
    # back out and what a user therefore copies -- not the raw ISO string.
    written_ts = datetime.fromisoformat(ev.timestamp).strftime("%Y-%m-%d %H:%M:%S")
    before = _git(["rev-list", "--count", "HEAD"], d).stdout.strip()
    tm = bt.TrustManager()
    assert tm.mark_override(written_ts, "operator disagreed") is True
    after = _git(["rev-list", "--count", "HEAD"], d).stdout.strip()
    assert int(after) > int(before), "the override was written but never committed"


def test_the_repository_is_initialised_once(ledger, caplog):
    """`_ensure_repo` re-runs forever while `.git` never appears."""
    _, d = ledger
    with caplog.at_level("INFO", logger=bt.__name__):
        bt.LedgerManager()
        bt.LedgerManager()
    inits = [r for r in caplog.records if "Initializing behavior ledger" in r.getMessage()]
    assert inits == [], f"re-initialised {len(inits)}x because .git never appeared"


def test_a_git_failure_is_reported_not_swallowed_as_success(ledger, caplog):
    """The `except` guard around the git calls must be reachable."""
    lm, d = ledger
    shutil.rmtree(d / ".git")          # repo gone; `git commit` must now fail
    with caplog.at_level("DEBUG", logger=bt.__name__):
        lm.append(_event("c.txt"))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "failed" in text.lower() or "error" in text.lower(), (
        "a git command that cannot succeed produced no failure record"
    )


def test_a_filesystem_event_reaches_the_websocket_broadcast():
    """`on_event` fires on the observer thread, where get_event_loop() raises."""
    # `from ... import behavior_router` resolves to the APIRouter object the
    # module exports under that same name, not the module. Import by path.
    import importlib

    br = importlib.import_module("weebot.interfaces.web.routers.behavior_router")

    delivered: list[bt.BehaviorEvent] = []

    async def scenario():
        async def fake_broadcast(event):
            delivered.append(event)

        loop = asyncio.get_running_loop()
        captured = {}

        def fake_create_tracker(session_id, watch_dir, on_event):
            captured["on_event"] = on_event
            tracker = type("T", (), {"start": lambda self: None, "stop": lambda self: None})()
            return tracker

        import unittest.mock as m
        with m.patch.object(br, "broadcast_event", fake_broadcast), \
             m.patch.object(br, "create_tracker", fake_create_tracker):
            await br.start_session_tracking("s1", str(loop and "."))
            # Fire the callback from a foreign thread, exactly as watchdog does.
            done = threading.Event()
            def observer_thread():
                captured["on_event"](_event("watched.txt"))
                done.set()
            threading.Thread(target=observer_thread, name="Thread-observer").start()
            await asyncio.get_running_loop().run_in_executor(None, done.wait)
            for _ in range(20):
                if delivered:
                    break
                await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert delivered, "the event never reached broadcast_event"


def test_concurrent_appends_are_all_committed():
    """Entries share one daily file, so commits interleave. None may be lost.

    12 threads appending at once produced 12 entries, 3 commits and 10 warnings
    reading "NOT version-controlled" -- while `git status` was clean and every
    entry was in fact committed. A peer's commit legitimately carries this
    entry's text, and `git commit` then exits 1 with "nothing to commit". The
    property to assert is therefore not one commit per entry, which the design
    never promised, but that nothing is left uncommitted and every entry's text
    is in the committed tree.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "ledger"
        d.mkdir()
        original, bt.LEDGER_DIR = bt.LEDGER_DIR, d
        try:
            lm = bt.LedgerManager()
            errors: list[str] = []

            def work(i: int) -> None:
                try:
                    lm.append(_event(f"c{i}.txt"))
                except Exception as exc:  # pragma: no cover - defensive
                    errors.append(f"{type(exc).__name__}: {exc}")

            threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            assert errors == [], errors
            assert _git(["fsck"], d).returncode == 0, "repository corrupted"
            assert _git(["status", "--porcelain"], d).stdout.strip() == "", (
                "entries were written but left uncommitted"
            )
            ledgers = [f for f in d.glob("*.md") if f.name != "README.md"]
            assert ledgers, "no ledger file written"
            at_head = "".join(_git(["show", f"HEAD:{f.name}"], d).stdout for f in ledgers)
            absent = [i for i in range(12) if f"c{i}.txt" not in at_head]
            assert absent == [], f"entries missing from the committed tree: {absent}"
        finally:
            bt.LEDGER_DIR = original


# --------------------------------------------------------------------------
# Controls -- these must pass both before and after the fix
# --------------------------------------------------------------------------

def test_the_markdown_entry_is_still_written(ledger):
    lm, d = ledger
    ev = _event("d.txt")
    assert lm.append(ev) is True
    files = list(d.glob("*.md"))
    assert files, "no ledger file written"
    assert "d.txt" in "\n".join(f.read_text() for f in files)


def test_a_watchdog_double_fire_is_still_deduplicated(ledger):
    """`modified` within 1s of `created` for the same path is a double-fire."""
    lm, _ = ledger
    assert lm.append(_event("e.txt", "created")) is True
    assert lm.append(_event("e.txt", "modified")) is False, "deduplication stopped working"


def test_append_still_reports_whether_it_wrote(ledger):
    lm, _ = ledger
    assert lm.append(_event("f.txt")) is True
