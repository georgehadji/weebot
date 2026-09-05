"""Wave 7 of the V7 defect hunt — sqlite connection lifecycle.

``sqlite3.Connection.__exit__`` commits or rolls back the transaction. It does
**not** close the connection. Every ``with sqlite3.connect(...) as conn:`` block
therefore leaked a connection and its file descriptor, once per call --
37 sites across 10 modules, several of them on hot paths (the scheduler polls,
the checkpoint store writes per step).

Demonstrated before the fix: executing on ``conn`` after the ``with`` block
still succeeded.

The fix is ``with closing(sqlite3.connect(...)) as conn, conn:`` -- ``closing``
shuts the connection, and the inner ``conn`` preserves the commit/rollback
semantics the code already relied on.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import subprocess

import pytest


class TestTheContextManagerDoesNotClose:
    """Pin the stdlib behaviour the defect rests on, so the gate below is meaningful."""

    def test_with_block_leaves_the_connection_open(self, tmp_path):
        db = str(tmp_path / "t.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE t (x INTEGER)")

        conn.execute("INSERT INTO t VALUES (1)")  # must NOT raise
        conn.close()

    def test_closing_does_close_it(self, tmp_path):
        from contextlib import closing

        db = str(tmp_path / "t.db")
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("CREATE TABLE t (x INTEGER)")

        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("INSERT INTO t VALUES (1)")

    def test_closing_still_commits(self, tmp_path):
        """The inner `conn` must keep the transaction semantics."""
        from contextlib import closing

        db = str(tmp_path / "t.db")
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (7)")

        with closing(sqlite3.connect(db)) as check, check:
            assert check.execute("SELECT x FROM t").fetchone() == (7,)

    def test_closing_still_rolls_back(self, tmp_path):
        from contextlib import closing

        db = str(tmp_path / "t.db")
        with closing(sqlite3.connect(db)) as setup, setup:
            setup.execute("CREATE TABLE t (x INTEGER PRIMARY KEY)")

        # sqlite returns NULL for division by zero rather than raising, so the
        # rollback has to be driven by a real constraint violation.
        with pytest.raises(sqlite3.IntegrityError):
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute("INSERT INTO t VALUES (1)")
                conn.execute("INSERT INTO t VALUES (1)")  # duplicate primary key

        with closing(sqlite3.connect(db)) as check, check:
            assert check.execute("SELECT COUNT(*) FROM t").fetchone() == (0,)


class TestNoLeakingConnectSitesRemain:
    """The ratchet: a new `with sqlite3.connect(...)` must not reappear."""

    @staticmethod
    def _repo_root() -> pathlib.Path:
        return pathlib.Path(__file__).resolve().parents[4]

    def _sites(self) -> list[str]:
        root = self._repo_root()
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "with sqlite3.connect(", "weebot/", "cli/"],
            cwd=root, capture_output=True, text=True,
        )
        return [
            line for line in result.stdout.splitlines()
            if line.strip() and "GitNexus" not in line
        ]

    def test_the_scan_works(self):
        """Guard the guard: the repo must still contain sqlite usage to scan."""
        root = self._repo_root()
        result = subprocess.run(
            ["grep", "-rln", "--include=*.py", "sqlite3.connect(", "weebot/"],
            cwd=root, capture_output=True, text=True,
        )
        assert len(result.stdout.split()) >= 5, "scan found almost nothing — check the pattern"

    def test_no_bare_connect_context_manager(self):
        sites = self._sites()
        assert sites == [], (
            "sqlite3's context manager commits but does not close. Use "
            "`with closing(sqlite3.connect(...)) as conn, conn:` instead.\n"
            + "\n".join(sites)
        )
