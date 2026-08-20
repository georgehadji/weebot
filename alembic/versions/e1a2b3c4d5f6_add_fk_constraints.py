"""add_fk_constraints

Revision ID: e1a2b3c4d5f6
Revises: 548511c41c39
Create Date: 2026-07-21 08:30:00.000000

Add ON DELETE CASCADE foreign keys for referential integrity when
sessions are deleted.
"""

from typing import Union
from collections.abc import Sequence

from alembic import op

revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "548511c41c39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table: str) -> bool:
    row = bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_names(bind, table: str) -> list[str]:
    return [r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")')]


def _copy_rows(bind, src: str, dst: str, fallbacks: dict[str, str] | None = None) -> None:
    """Copy *src* rows into *dst*, matching on column NAME rather than position.

    The original implementation used ``INSERT INTO dst SELECT * FROM src``,
    which requires both tables to have identical column count and order. That
    held only for databases where the source table had already been widened by
    application code; on a database built from ``548511c41c39`` the source has
    8 columns and the destination 14, so the migration aborted with
    "table behavioral_rules_new has 14 columns but 8 values were supplied"
    and no fresh database could ever be migrated.

    Columns present in both tables are copied. Columns that exist only in the
    destination fall back to *fallbacks* (destination column -> source column)
    when given, and otherwise take their schema DEFAULT. Columns that exist
    only in the source are dropped — no attempt is made to guess a rename.
    """
    src_cols = _column_names(bind, src)
    dst_cols = _column_names(bind, dst)

    insert_cols: list[str] = []
    select_cols: list[str] = []
    for col in dst_cols:
        if col in src_cols:
            source_expr = col
        elif fallbacks and col in fallbacks and fallbacks[col] in src_cols:
            source_expr = fallbacks[col]
        else:
            continue  # rely on the DEFAULT declared on dst
        insert_cols.append(f'"{col}"')
        select_cols.append(f'"{source_expr}"')

    if not insert_cols:
        return

    bind.exec_driver_sql(
        f'INSERT INTO "{dst}" ({", ".join(insert_cols)}) '
        f'SELECT {", ".join(select_cols)} FROM "{src}"'
    )


def upgrade() -> None:
    """Add FK constraints with ON DELETE CASCADE on session-scoped tables.

    This ensures that when a session is deleted via the cascading orchestrator,
    related rows in behavioral_rules, commitments, and other cross-reference
    tables are automatically cleaned up at the database level.

    Uses ALTER TABLE … RENAME → CREATE → INSERT → DROP to work around
    SQLite's limited ALTER TABLE support.

    The rebuilt tables keep exactly the columns the application reads and
    writes — see ``sqlite_state_repo._ensure_schema`` and
    ``_behavioral_rule_repo``. Only the FOREIGN KEY is added. An earlier
    version of this migration replaced both tables with unrelated column
    sets (rule_type/trigger_condition/salience_score…, and
    commitment_type/statement/actor…), which left the application writing
    to columns that no longer existed.

    Tables affected:
        - behavioral_rules.source_session_id → sessions.id ON DELETE CASCADE
        - commitments.source_session_id → sessions.id ON DELETE CASCADE

    Note: the cascade is declarative only for now — the sessions-database
    connection pool never issues ``PRAGMA foreign_keys = ON``, so SQLite
    does not enforce it at runtime.
    """
    bind = op.get_bind()

    # ── behavioral_rules ─────────────────────────────────────────────
    op.execute("PRAGMA foreign_keys = OFF")
    # A previously failed run can leave the scratch table behind, and the
    # container restarts into this migration on a loop — without the guard the
    # retry dies on "table behavioral_rules_new already exists" instead of
    # reporting the real error.
    op.execute("DROP TABLE IF EXISTS behavioral_rules_new")
    op.execute("""
        CREATE TABLE behavioral_rules_new (
            id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            source_session_id TEXT NOT NULL DEFAULT '',
            source_message TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'global',
            created_at TEXT NOT NULL,
            applied_count INTEGER NOT NULL DEFAULT 0,
            last_applied_at TEXT,
            FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
        """)
    _copy_rows(bind, "behavioral_rules", "behavioral_rules_new")
    op.execute("DROP TABLE behavioral_rules")
    op.execute("ALTER TABLE behavioral_rules_new RENAME TO behavioral_rules")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rules_src ON behavioral_rules(source_session_id)")
    op.execute("PRAGMA foreign_keys = ON")

    # ── commitments ──────────────────────────────────────────────────
    # Only run if the commitments table exists (it is created inline by
    # sqlite_state_repo.py, not in the initial Alembic schema).
    if _table_exists(bind, "commitments"):
        op.execute("PRAGMA foreign_keys = OFF")
        op.execute("DROP TABLE IF EXISTS commitments_new")
        op.execute("""
            CREATE TABLE commitments_new (
                id TEXT PRIMARY KEY,
                promise_text TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                source_session_id TEXT NOT NULL,
                source_event_id TEXT,
                due_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                failure_reason TEXT,
                FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """)
        _copy_rows(bind, "commitments", "commitments_new")
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
    bind = op.get_bind()

    # ── behavioral_rules ─────────────────────────────────────────────
    op.execute("PRAGMA foreign_keys = OFF")
    op.execute("DROP TABLE IF EXISTS behavioral_rules_old")
    op.execute("""
        CREATE TABLE behavioral_rules_old (
            id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            source_session_id TEXT NOT NULL DEFAULT '',
            source_message TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'global',
            created_at TEXT NOT NULL,
            applied_count INTEGER NOT NULL DEFAULT 0,
            last_applied_at TEXT
        )
        """)
    _copy_rows(bind, "behavioral_rules", "behavioral_rules_old")
    op.execute("DROP TABLE behavioral_rules")
    op.execute("ALTER TABLE behavioral_rules_old RENAME TO behavioral_rules")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rules_src ON behavioral_rules(source_session_id)")
    op.execute("PRAGMA foreign_keys = ON")

    # ── commitments ──────────────────────────────────────────────────
    if _table_exists(bind, "commitments"):
        op.execute("PRAGMA foreign_keys = OFF")
        op.execute("DROP TABLE IF EXISTS commitments_old")
        op.execute("""
            CREATE TABLE commitments_old (
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
            )
            """)
        _copy_rows(bind, "commitments", "commitments_old")
        op.execute("DROP TABLE commitments")
        op.execute("ALTER TABLE commitments_old RENAME TO commitments")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_commitments_src ON commitments(source_session_id)"
        )
        op.execute("PRAGMA foreign_keys = ON")
