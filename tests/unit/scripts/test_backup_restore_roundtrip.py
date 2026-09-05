"""Backup and restore, proven against the invariant rather than by example.

Phase B3 of tasks/specs/review_gate_and_residual_work_plan.md, closing the gap
`implementation_audit_report.md` §6 recorded and the V7 plan called *"the
highest-value place in the repo to add proof tests"*: `scripts/backup.py`,
`scripts/restore.py` and `_database_backup_job` had **no tests at all**, on a
subsystem whose last three defects were CRITICAL.

The property that matters is not that one database survives a round trip but
that *databases* do:

    restore(backup(db)) == db

so the round trip is property-based. A hand-written example asserts one shape;
a property finds the encoding, empty-table and large-blob cases nobody thinks
to write. Everything else in the plan's matrix — WAL safety, the integrity
interlock, the pre-restore net, retention, confirmation, and whether the
scheduled job surfaces failure — is example-based, because each is a specific
behaviour rather than a universally quantified claim.

The code is unusually testable and that is why this is small: both entry points
take `argv` explicitly, so the CLI is drivable in-process with no subprocess and
no monkeypatching of `sys.argv`.
"""

from __future__ import annotations

import importlib.util
import logging
import pathlib
import sqlite3
import tempfile
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = _load("backup")
restore = _load("restore")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SCHEMA = "CREATE TABLE t (a INTEGER, b TEXT, c REAL, d BLOB)"

# NaN is excluded deliberately: sqlite stores it as NULL, so a NaN round trip
# is not an equality failure of the backup -- it is sqlite's documented type
# behaviour, and asserting on it would be testing the wrong thing.
_VALUES = st.one_of(
    st.none(),
    st.integers(min_value=-(2**62), max_value=2**62),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    st.text(max_size=200),
    st.binary(max_size=512),
)
_ROWS = st.lists(st.tuples(_VALUES, _VALUES, _VALUES, _VALUES), max_size=25)


def _write_db(path: pathlib.Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        with conn:
            conn.execute(_SCHEMA)
            conn.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    finally:
        conn.close()


def _read_db(path: pathlib.Path) -> list[tuple]:
    conn = sqlite3.connect(str(path))
    try:
        return list(conn.execute("SELECT a, b, c, d FROM t"))
    finally:
        conn.close()


def _corrupt(path: pathlib.Path) -> None:
    """Damage the page data while leaving the sqlite header intact.

    Truncating or zeroing the header makes the file stop being a database,
    which `integrity_check` reports as an error rather than as corruption --
    a different path from the one the interlock guards.
    """
    data = bytearray(path.read_bytes())
    for i in range(4096, min(len(data), 16384)):
        data[i] ^= 0xFF
    path.write_bytes(bytes(data))


# ---------------------------------------------------------------------------
# the round-trip property
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(rows=_ROWS)
    def test_restore_of_a_backup_equals_the_original(self, rows):
        """restore(backup(db)) == db, for any table contents.

        Temporary directories are created inside the test rather than by a
        fixture: hypothesis re-runs the body many times per test, and a
        function-scoped fixture would be shared across all of those examples.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            src = root / "src.sqlite"
            dest_dir = root / "backups"
            dest_dir.mkdir()
            _write_db(src, rows)
            before = _read_db(src)

            backup_path = backup.backup_database(src, dest_dir, "prop")
            assert backup.verify_backup(backup_path)

            restored = root / "restored.sqlite"
            restore.restore(backup_path, restored)

            assert _read_db(restored) == before

    def test_an_empty_database_round_trips(self):
        """The boundary the property will rarely hit on its own."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            src = root / "src.sqlite"
            dest_dir = root / "b"
            dest_dir.mkdir()
            _write_db(src, [])

            path = backup.backup_database(src, dest_dir, "empty")
            restored = root / "r.sqlite"
            restore.restore(path, restored)
            assert _read_db(restored) == []

    def test_a_large_blob_round_trips(self):
        """Larger than one sqlite page, so it spills to overflow pages."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            src = root / "src.sqlite"
            dest_dir = root / "b"
            dest_dir.mkdir()
            blob = bytes(range(256)) * 400  # ~100 KiB
            _write_db(src, [(1, "x", 1.5, blob)])

            path = backup.backup_database(src, dest_dir, "blob")
            restored = root / "r.sqlite"
            restore.restore(path, restored)
            assert _read_db(restored) == [(1, "x", 1.5, blob)]


# ---------------------------------------------------------------------------
# WAL safety — the documented reason sqlite3.backup() is used over cp
# ---------------------------------------------------------------------------


class TestWalSafety:
    def test_backup_taken_during_an_open_uncommitted_write(self, tmp_path):
        """The claim `sqlite3.backup()` exists to support, never previously tested.

        A second connection holds an *uncommitted* transaction while the backup
        runs. The backup must reflect the last committed state — not the dirty
        write, and not a torn mixture.
        """
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(1, "committed", 1.0, b"x")])

        # The source must already be in WAL mode, as the live database is.
        # `backup_database` issues `PRAGMA journal_mode=WAL` on the source, and
        # *changing* the mode needs an exclusive lock -- so on a journal-mode
        # database with a writer mid-transaction the backup fails outright with
        # "database is locked", the very case sqlite3.backup() was chosen for.
        # See the residual risk in tasks/audits/residual_b3_backup_restore.md.
        _conn = sqlite3.connect(str(src))
        try:
            _conn.execute("PRAGMA journal_mode=WAL;")
        finally:
            _conn.close()

        writer = sqlite3.connect(str(src))
        try:
            writer.execute("BEGIN")
            writer.execute("INSERT INTO t VALUES (?, ?, ?, ?)", (2, "dirty", 2.0, b"y"))
            # Not committed. The backup must not see it.
            path = backup.backup_database(src, dest_dir, "wal")
            writer.rollback()
        finally:
            writer.close()

        assert backup.verify_backup(path)
        assert _read_db(path) == [(1, "committed", 1.0, b"x")]


# ---------------------------------------------------------------------------
# the integrity interlock
# ---------------------------------------------------------------------------


class TestIntegrityGate:
    def test_a_corrupt_backup_is_refused_by_restore(self, tmp_path):
        """If this gate failed open, restore would destroy the destination."""
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(i, f"row{i}", float(i), b"z") for i in range(200)])
        path = backup.backup_database(src, dest_dir, "gate")
        _corrupt(path)

        assert restore.verify_backup(path) is False

        live = tmp_path / "live.sqlite"
        _write_db(live, [(99, "precious", 9.0, b"keep")])
        code = restore.main(["--backup", str(path), "--dest", str(live), "--force"])

        assert code == 2, "a corrupt backup must not be restored"
        assert _read_db(live) == [(99, "precious", 9.0, b"keep")], "destination was destroyed"

    def test_backup_verification_failure_is_reported_by_the_exit_code(self, tmp_path):
        """`backup.main` returns 3 when its own verification fails.

        That non-zero code is what `_database_backup_job` keys its error log on,
        so it is the link between a bad backup and anybody finding out.
        """
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(1, "a", 1.0, b"b")])

        original = backup.verify_backup
        try:
            backup.verify_backup = lambda _p: False
            code = backup.main(
                ["--db", str(src), "--dest", str(dest_dir), "--label", "x", "--no-metrics"]
            )
        finally:
            backup.verify_backup = original
        assert code == 3


# ---------------------------------------------------------------------------
# the pre-restore safety net
# ---------------------------------------------------------------------------


class TestPreRestoreNet:
    def test_the_previous_destination_is_kept_and_is_itself_restorable(self, tmp_path):
        """Documented as the recovery path for a mistaken restore.

        Keeping the file is not enough — it has to still be a working database,
        which is the part that would silently not hold if the rename were ever
        replaced by a copy of the wrong thing.
        """
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(1, "new", 1.0, b"n")])
        path = backup.backup_database(src, dest_dir, "net")

        live = tmp_path / "live.sqlite"
        _write_db(live, [(2, "old", 2.0, b"o")])

        pre_bak = restore.restore(path, live)

        assert pre_bak is not None and pre_bak.exists()
        assert _read_db(live) == [(1, "new", 1.0, b"n")]
        assert _read_db(pre_bak) == [(2, "old", 2.0, b"o")]

        # And the net can be used: restoring it back undoes the mistake.
        restore.restore(pre_bak, live)
        assert _read_db(live) == [(2, "old", 2.0, b"o")]

    def test_no_net_is_written_when_the_destination_did_not_exist(self, tmp_path):
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(1, "a", 1.0, b"b")])
        path = backup.backup_database(src, dest_dir, "net2")

        assert restore.restore(path, tmp_path / "fresh.sqlite") is None


# ---------------------------------------------------------------------------
# retention — deletion logic on a directory of backups
# ---------------------------------------------------------------------------


class TestRetention:
    @staticmethod
    def _aged(dest_dir: pathlib.Path, label: str, name: str, days_old: float) -> pathlib.Path:
        path = dest_dir / f"{label}_{name}.sqlite"
        path.write_bytes(b"")
        stamp = time.time() - days_old * 86400
        import os

        os.utime(path, (stamp, stamp))
        return path

    def test_older_go_and_newer_stay(self, tmp_path):
        old = self._aged(tmp_path, "keep", "old", 40)
        new = self._aged(tmp_path, "keep", "new", 1)

        assert backup.prune_old_backups(tmp_path, "keep", 30) == 1
        assert not old.exists()
        assert new.exists()

    def test_zero_retention_keeps_everything(self, tmp_path):
        """The off-by-one with the highest consequence in the file."""
        old = self._aged(tmp_path, "keep", "ancient", 10_000)
        assert backup.prune_old_backups(tmp_path, "keep", 0) == 0
        assert old.exists()

    def test_negative_retention_keeps_everything(self, tmp_path):
        old = self._aged(tmp_path, "keep", "ancient", 10_000)
        assert backup.prune_old_backups(tmp_path, "keep", -1) == 0
        assert old.exists()

    def test_another_label_is_untouched(self, tmp_path):
        """Pruning one label must not reach into another's backups."""
        mine = self._aged(tmp_path, "mine", "old", 40)
        theirs = self._aged(tmp_path, "theirs", "old", 40)

        assert backup.prune_old_backups(tmp_path, "mine", 30) == 1
        assert not mine.exists()
        assert theirs.exists(), "pruning crossed a label boundary"


# ---------------------------------------------------------------------------
# confirmation — the guard on an irreversible action
# ---------------------------------------------------------------------------


class TestConfirmation:
    def test_declining_the_prompt_leaves_the_destination_alone(self, tmp_path, monkeypatch):
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(1, "new", 1.0, b"n")])
        path = backup.backup_database(src, dest_dir, "confirm")

        live = tmp_path / "live.sqlite"
        _write_db(live, [(2, "old", 2.0, b"o")])

        monkeypatch.setattr("builtins.input", lambda *_: "n")
        code = restore.main(["--backup", str(path), "--dest", str(live)])

        assert code == 0
        assert _read_db(live) == [(2, "old", 2.0, b"o")], "declined restore overwrote anyway"

    def test_force_skips_the_prompt(self, tmp_path, monkeypatch):
        src = tmp_path / "src.sqlite"
        dest_dir = tmp_path / "b"
        dest_dir.mkdir()
        _write_db(src, [(1, "new", 1.0, b"n")])
        path = backup.backup_database(src, dest_dir, "force")

        live = tmp_path / "live.sqlite"
        _write_db(live, [(2, "old", 2.0, b"o")])

        def _no_prompt(*_):
            raise AssertionError("--force must not prompt")

        monkeypatch.setattr("builtins.input", _no_prompt)
        assert restore.main(["--backup", str(path), "--dest", str(live), "--force"]) == 0
        assert _read_db(live) == [(1, "new", 1.0, b"n")]

    def test_a_missing_backup_file_is_refused(self, tmp_path):
        code = restore.main(
            ["--backup", str(tmp_path / "nope.sqlite"), "--dest", str(tmp_path / "d"), "--force"]
        )
        assert code == 1


# ---------------------------------------------------------------------------
# the scheduled job — the purest C2 candidate in the subsystem
# ---------------------------------------------------------------------------


class TestScheduledJobSurfacesFailure:
    """A backup job that fails silently is indistinguishable from one that works.

    Whatever else is deferred, this assertion should not be: nobody learns the
    backups stopped until the day a restore is needed.
    """

    async def test_a_failing_backup_is_logged_at_error(self, tmp_path, monkeypatch, caplog):
        from weebot.scheduling import default_jobs

        monkeypatch.setenv("WEEBOT_SESSIONS_DB", str(tmp_path / "does-not-matter.sqlite"))
        monkeypatch.setenv("WEEBOT_BACKUP_DIR", str(tmp_path / "backups"))

        class _Proc:
            returncode = 3

            async def communicate(self):
                return b"", b"integrity check failed"

        async def _fake_exec(*_args, **_kwargs):
            return _Proc()

        monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

        with caplog.at_level(logging.ERROR):
            await default_jobs._database_backup_job()

        assert any(
            "FAILED" in r.message or "FAILED" in r.getMessage() for r in caplog.records
        ), "a non-zero backup exit produced no ERROR record"

    async def test_a_backup_that_cannot_start_is_logged_at_error(
        self, tmp_path, monkeypatch, caplog
    ):
        from weebot.scheduling import default_jobs

        monkeypatch.setenv("WEEBOT_SESSIONS_DB", str(tmp_path / "db.sqlite"))
        monkeypatch.setenv("WEEBOT_BACKUP_DIR", str(tmp_path / "backups"))

        async def _boom(*_args, **_kwargs):
            raise OSError("no such executable")

        monkeypatch.setattr("asyncio.create_subprocess_exec", _boom)

        with caplog.at_level(logging.ERROR):
            await default_jobs._database_backup_job()

        assert any("failed to start" in r.getMessage() for r in caplog.records)


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
