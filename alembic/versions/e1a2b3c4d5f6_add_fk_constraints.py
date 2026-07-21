"""add_fk_constraints

Revision ID: e1a2b3c4d5f6
Revises: 548511c41c39
Create Date: 2026-07-21 08:30:00.000000

Add ON DELETE CASCADE foreign keys for referential integrity when
sessions are deleted.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "548511c41c39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add FK constraints with ON DELETE CASCADE on session-scoped tables.

    This ensures that when a session is deleted via the cascading orchestrator,
    related rows in behavioral_rules, commitments, and other cross-reference
    tables are automatically cleaned up at the database level.

    Uses ALTER TABLE … RENAME → CREATE → INSERT → DROP to work around
    SQLite's limited ALTER TABLE support.

    Tables affected:
        - behavioral_rules.source_session_id → sessions.id ON DELETE CASCADE
        - commitments.source_session_id → sessions.id ON DELETE CASCADE
    """
    # ── behavioral_rules ─────────────────────────────────────────────
    op.execute("PRAGMA foreign_keys = OFF")
    op.execute(
        """
        CREATE TABLE behavioral_rules_new (
            id TEXT PRIMARY KEY,
            rule_type TEXT NOT NULL DEFAULT 'behavioral_rule',
            rule_text TEXT NOT NULL DEFAULT '',
            trigger_condition TEXT NOT NULL DEFAULT '',
            action_text TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'medium',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_session_id TEXT NOT NULL,
            salience_score REAL NOT NULL DEFAULT 0.0,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            feedback_score INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "INSERT INTO behavioral_rules_new SELECT * FROM behavioral_rules"
    )
    op.execute("DROP TABLE behavioral_rules")
    op.execute("ALTER TABLE behavioral_rules_new RENAME TO behavioral_rules")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rules_src ON behavioral_rules(source_session_id)"
    )
    op.execute("PRAGMA foreign_keys = ON")

    # ── commitments ──────────────────────────────────────────────────
    # Only run if the commitments table exists (it is created inline by
    # sqlite_state_repo.py, not in the initial Alembic schema).
    result = op.get_bind().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='commitments'"
    ).fetchone()
    if result is not None:
        op.execute("PRAGMA foreign_keys = OFF")
        op.execute(
            """
            CREATE TABLE commitments_new (
                id TEXT PRIMARY KEY,
                commitment_type TEXT NOT NULL DEFAULT 'commitment',
                source_session_id TEXT NOT NULL,
                statement TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT 'weebot',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                completed_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """
        )
        op.execute(
            "INSERT INTO commitments_new SELECT * FROM commitments"
        )
        op.execute("DROP TABLE commitments")
        op.execute("ALTER TABLE commitments_new RENAME TO commitments")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_commitments_src ON commitments(source_session_id)"
        )
        op.execute("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    """Remove FK constraints — recreates tables without referential integrity.

    Warning: This drops and recreates tables, preserving existing rows.
    Foreign key enforcement is lost after downgrade.
    """
    # ── behavioral_rules ─────────────────────────────────────────────
    op.execute("PRAGMA foreign_keys = OFF")
    op.execute(
        """
        CREATE TABLE behavioral_rules_old (
            id TEXT PRIMARY KEY,
            rule_type TEXT NOT NULL DEFAULT 'behavioral_rule',
            rule_text TEXT NOT NULL DEFAULT '',
            trigger_condition TEXT NOT NULL DEFAULT '',
            action_text TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'medium',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_session_id TEXT NOT NULL,
            salience_score REAL NOT NULL DEFAULT 0.0,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            feedback_score INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        "INSERT INTO behavioral_rules_old SELECT * FROM behavioral_rules"
    )
    op.execute("DROP TABLE behavioral_rules")
    op.execute("ALTER TABLE behavioral_rules_old RENAME TO behavioral_rules")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rules_src ON behavioral_rules(source_session_id)"
    )
    op.execute("PRAGMA foreign_keys = ON")

    # ── commitments ──────────────────────────────────────────────────
    result = op.get_bind().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='commitments'"
    ).fetchone()
    if result is not None:
        op.execute("PRAGMA foreign_keys = OFF")
        op.execute(
            """
            CREATE TABLE commitments_old (
                id TEXT PRIMARY KEY,
                commitment_type TEXT NOT NULL DEFAULT 'commitment',
                source_session_id TEXT NOT NULL,
                statement TEXT NOT NULL DEFAULT '',
                actor TEXT NOT NULL DEFAULT 'weebot',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                completed_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        op.execute(
            "INSERT INTO commitments_old SELECT * FROM commitments"
        )
        op.execute("DROP TABLE commitments")
        op.execute("ALTER TABLE commitments_old RENAME TO commitments")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_commitments_src ON commitments(source_session_id)"
        )
        op.execute("PRAGMA foreign_keys = ON")
