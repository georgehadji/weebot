"""SQLite-backed misalignment journal."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from weebot.application.ports.misalignment_journal_port import MisalignmentJournalPort
from weebot.domain.models.misalignment_entry import MisalignmentEntry

_log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS misalignment_journal (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    project_path     TEXT NOT NULL,
    symptom          TEXT NOT NULL,
    constraint_text  TEXT,
    step_description TEXT,
    correction_text  TEXT,
    created_at       TEXT NOT NULL
)
"""

_INSERT = """
INSERT OR REPLACE INTO misalignment_journal
    (id, session_id, project_path, symptom, constraint_text,
     step_description, correction_text, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_RECENT = """
SELECT id, session_id, project_path, symptom, constraint_text,
       step_description, correction_text, created_at
FROM misalignment_journal
WHERE project_path = ?
ORDER BY created_at DESC
LIMIT ?
"""


class SQLiteMisalignmentJournal(MisalignmentJournalPort):
    """Stores misalignment entries in the weebot SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        try:
            self._ensure_table()
        except Exception as exc:
            _log.warning("MisalignmentJournal: could not initialise table: %s", exc)

    def _ensure_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_TABLE)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_TABLE)
        return conn

    async def record(self, entry: MisalignmentEntry) -> None:
        try:
            with self._connect() as conn:
                conn.execute(_INSERT, (
                    entry.id,
                    entry.session_id,
                    entry.project_path,
                    entry.symptom,
                    entry.constraint_text,
                    entry.step_description,
                    entry.correction_text,
                    entry.created_at.isoformat(),
                ))
                conn.commit()
        except Exception as exc:
            _log.warning("MisalignmentJournal.record failed: %s", exc)

    async def get_recent(
        self, project_path: str, limit: int = 5
    ) -> list[MisalignmentEntry]:
        try:
            with self._connect() as conn:
                rows = conn.execute(_SELECT_RECENT, (project_path, limit)).fetchall()
            return [
                MisalignmentEntry(
                    id=r[0],
                    session_id=r[1],
                    project_path=r[2],
                    symptom=r[3],
                    constraint_text=r[4],
                    step_description=r[5],
                    correction_text=r[6],
                    created_at=r[7],
                )
                for r in rows
            ]
        except Exception as exc:
            _log.warning("MisalignmentJournal.get_recent failed: %s", exc)
            return []
