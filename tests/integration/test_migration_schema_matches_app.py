"""Migrated schema must match what the application actually reads and writes.

Regression test for the mismatch found on 2026-08-05: migration
``e1a2b3c4d5f6_add_fk_constraints`` is documented as only adding
``ON DELETE CASCADE`` foreign keys, but it rebuilt ``behavioral_rules`` and
``commitments`` with entirely different column sets
(``rule_type``/``trigger_condition``/``salience_score``… and
``commitment_type``/``statement``/``actor``…).

Nothing caught it because:

  - the migration crashed before reaching that point on a fresh database,
    so the schema was never actually produced; and
  - the Docker smoke test only probes ``/api/health``, which does not touch
    behavioural rules or commitments.

Once the crash was fixed the migration ran, and
``_behavioral_rule_repo.save()`` — which inserts ``source_message`` and
``scope`` — would have failed against the migrated table.

These tests run the real migration chain against a temporary database and
assert the resulting columns are a superset of what the application writes,
so a future divergence fails here instead of at runtime.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]

# Columns the application depends on. Sources:
#   behavioral_rules -> infrastructure/persistence/sqlite_state_repo.py
#                       + _behavioral_rule_repo.save()
#   commitments      -> infrastructure/persistence/sqlite_state_repo.py
APP_BEHAVIORAL_RULES_COLUMNS = {
    "id",
    "rule_text",
    "source_session_id",
    "source_message",
    "scope",
    "created_at",
    "applied_count",
    "last_applied_at",
}

APP_COMMITMENTS_COLUMNS = {
    "id",
    "promise_text",
    "context",
    "source_session_id",
    "source_event_id",
    "due_at",
    "status",
    "created_at",
    "updated_at",
    "failure_reason",
}


def _config(db_path: Path) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _point_settings_at(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    """Redirect the migration environment at *db_path*.

    alembic/env.py overrides sqlalchemy.url with
    ``weebot.config.settings.SESSIONS_DB``, so setting the URL on the Config
    alone is not enough — and SESSIONS_DB is resolved from the environment at
    import time, so setting the env var after import has no effect either.
    Patching the module attribute is what actually takes, and keeps every test
    on its own tmp_path database instead of the developer's real one.
    """
    monkeypatch.setenv("WEEBOT_SESSIONS_DB", str(db_path))
    monkeypatch.setattr("weebot.config.settings.SESSIONS_DB", str(db_path))


def _migrate(db_path: Path) -> None:
    command.upgrade(_config(db_path), "head")


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    finally:
        conn.close()


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "sessions.db"
    _point_settings_at(monkeypatch, db_path)
    _migrate(db_path)
    return db_path


def test_migrations_apply_to_an_empty_database(migrated_db: Path) -> None:
    """The whole chain must run from scratch, not just from a live database."""
    assert migrated_db.exists()
    conn = sqlite3.connect(migrated_db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "behavioral_rules" in tables


def test_behavioral_rules_keeps_the_columns_the_app_writes(migrated_db: Path) -> None:
    missing = APP_BEHAVIORAL_RULES_COLUMNS - _columns(migrated_db, "behavioral_rules")
    assert not missing, (
        f"migrated behavioral_rules is missing columns the application writes: "
        f"{sorted(missing)}"
    )


def test_behavioral_rule_insert_statement_still_works(migrated_db: Path) -> None:
    """Exercise the exact INSERT from _behavioral_rule_repo.save()."""
    conn = sqlite3.connect(migrated_db)
    try:
        conn.execute(
            "INSERT INTO sessions (id, user_id, agent_id, status, created_at, updated_at) "
            "VALUES ('s1', 'u', 'a', 'completed', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            """
            INSERT INTO behavioral_rules
                (id, rule_text, source_session_id, source_message, scope, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                rule_text = excluded.rule_text,
                scope = excluded.scope
            """,
            ("r1", "never do X", "s1", "please stop doing X", "global", "2026-01-02"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT rule_text, source_message, scope, applied_count FROM behavioral_rules"
        ).fetchone()
    finally:
        conn.close()

    assert row == ("never do X", "please stop doing X", "global", 0)


def test_commitments_keeps_the_columns_the_app_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """commitments is created by application code, so seed it before migrating."""
    db_path = tmp_path / "sessions_with_commitments.db"
    _point_settings_at(monkeypatch, db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                status TEXT NOT NULL, title TEXT,
                events_json TEXT NOT NULL DEFAULT '[]',
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE commitments (
                id TEXT PRIMARY KEY,
                promise_text TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                source_session_id TEXT NOT NULL,
                source_event_id TEXT,
                due_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                failure_reason TEXT
            );
            CREATE TABLE behavioral_rules (
                id TEXT PRIMARY KEY,
                rule_text TEXT NOT NULL,
                source_session_id TEXT NOT NULL DEFAULT '',
                source_message TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT 'global',
                created_at TEXT NOT NULL,
                applied_count INTEGER NOT NULL DEFAULT 0,
                last_applied_at TEXT
            );
            """)
        conn.execute(
            "INSERT INTO sessions (id, user_id, agent_id, status, created_at, updated_at) "
            "VALUES ('s1', 'u', 'a', 'completed', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO commitments (id, promise_text, source_session_id, created_at, updated_at) "
            "VALUES ('c1', 'I will follow up', 's1', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
    finally:
        conn.close()

    # Stamp the base revision so only the FK migration and later ones run —
    # 548511c41c39 would otherwise try to recreate `sessions`.
    cfg = _config(db_path)
    command.stamp(cfg, "548511c41c39")
    command.upgrade(cfg, "head")

    missing = APP_COMMITMENTS_COLUMNS - _columns(db_path, "commitments")
    assert (
        not missing
    ), f"migrated commitments is missing columns the application writes: {sorted(missing)}"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, promise_text, source_session_id, status FROM commitments"
        ).fetchone()
    finally:
        conn.close()
    # Data must survive the rebuild intact — the previous positional
    # `INSERT ... SELECT *` silently shifted promise_text into commitment_type.
    assert row == ("c1", "I will follow up", "s1", "pending")
