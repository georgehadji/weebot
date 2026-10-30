"""L3 cleanup (plan 2026-10-29): the one-off script that removes phantom event-store sessions.

Before the L3 fix, an event with no session id was journaled under its own id, and
``log_event`` created a sessions row for it. A phantom is a session whose every event is
named after itself and carries an empty ``session_id``. The script counts them by default
and deletes them only with ``--apply``.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "purge_phantom_sessions", Path("scripts/purge_phantom_sessions.py")
)
purge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(purge)

_SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, status TEXT);
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    event_type TEXT NOT NULL, data_json TEXT NOT NULL
);
"""


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "events.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)

    def add(session: str, event_id: str, payload_session: str) -> None:
        conn.execute("INSERT OR IGNORE INTO sessions (id) VALUES (?)", (session,))
        data = json.dumps({"id": event_id, "session_id": payload_session})
        conn.execute(
            "INSERT INTO events (session_id, event_type, data_json) VALUES (?, 'tool', ?)",
            (session, data),
        )

    add("real-1", "e1", "real-1")  # a real run
    add("real-1", "e2", "real-1")
    add("p1", "p1", "")  # phantoms: named after their own event, no session in the payload
    add("p2", "p2", "")
    add("p2", "p2", "")  # the same event journaled twice
    add("odd", "odd", "odd")  # names itself but has a session id: not a phantom
    conn.commit()
    conn.close()
    return path


def _ids(path: Path) -> tuple[list[str], int]:
    conn = sqlite3.connect(path)
    sessions = [r[0] for r in conn.execute("SELECT id FROM sessions ORDER BY id")]
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    return sessions, events


def test_dry_run_counts_and_changes_nothing(db):
    assert purge.main(["--db", str(db)]) == 0
    assert purge.count(db) == (2, 3)
    assert _ids(db) == (["odd", "p1", "p2", "real-1"], 6)


def test_apply_removes_only_the_phantoms(db):
    assert purge.main(["--db", str(db), "--apply"]) == 0
    assert _ids(db) == (["odd", "real-1"], 3)
    assert purge.count(db) == (0, 0)


def test_a_missing_database_is_an_error(tmp_path):
    assert purge.main(["--db", str(tmp_path / "nope.db")]) == 1
