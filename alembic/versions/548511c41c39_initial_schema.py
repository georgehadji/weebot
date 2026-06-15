"""initial_schema

Revision ID: 548511c41c39
Revises: 
Create Date: 2026-06-12 13:32:58.668007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '548511c41c39'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial schema.

    Tables managed by sqlite_state_repo.py ("weebot_sessions.db"):
    - sessions: Agent session state with events_json and context_json.
    - pending_opportunities: Capability-7 task proposals.
    - behavioral_rules: Learned agent behavior rules.
    - events_fts: FTS5 full-text search over session events.

    Note: Independent stores (event_store.py -> ~/.weebot/events.db,
    sqlite_knowledge_graph.py, sqlite_misalignment_journal.py, etc.) each
    manage their own databases and are NOT covered by this migration.
    """
    # ── Sessions table ─────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT,
            events_json TEXT NOT NULL DEFAULT '[]',
            context_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)"
    )

    # ── Pending opportunities ───────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_opportunities (
            id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            source TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.0,
            estimated_effort TEXT NOT NULL DEFAULT 'medium',
            created_at TEXT NOT NULL,
            presented INTEGER NOT NULL DEFAULT 0,
            accepted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_opp_presented ON pending_opportunities(presented)"
    )

    # ── Behavioral rules ────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS behavioral_rules (
            id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            source_session_id TEXT NOT NULL DEFAULT '',
            source_message TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'global',
            created_at TEXT NOT NULL,
            applied_count INTEGER NOT NULL DEFAULT 0,
            last_applied_at TEXT
        )
        """
    )

    # ── FTS5 virtual table for event search ─────────────
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            session_id,
            event_data,
            content=''
        )
        """
    )

    # ── Jobs table (scheduler) ──────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            trigger_type TEXT NOT NULL,
            trigger_config TEXT NOT NULL,
            command TEXT,
            callable_name TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_run TEXT,
            next_run TEXT,
            run_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_error TEXT,
            enabled INTEGER DEFAULT 1
        )
        """
    )


def downgrade() -> None:
    """Downgrade by dropping all managed tables.

    Warning: This drops ALL data in the managed tables.
    Individually managed stores (events.db, knowledge_graph, etc.)
    are unaffected.
    """
    op.execute("DROP TABLE IF EXISTS events_fts")
    op.execute("DROP TABLE IF EXISTS behavioral_rules")
    op.execute("DROP TABLE IF EXISTS pending_opportunities")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS jobs")
