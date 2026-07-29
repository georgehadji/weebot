"""consolidate_core_schema — capture all core tables under Alembic governance

Revision ID: c0re_5ch3m4_v1
Revises: e1a2b3c4d5f6
Create Date: 2026-07-29

This migration captures ALL core tables that were previously created via
runtime ``CREATE TABLE IF NOT EXISTS`` in individual modules.  With this
migration applied, those modules can safely skip their DDL and rely on
Alembic for schema management.

Tables consolidated:
- flow_checkpoints   (was checkpoint_store.py)
- gateway_sessions   (was gateway_session_store.py)
- jobs               (was scheduling/scheduler.py)

Note: The following tables were already covered by prior migrations:
- sessions, pending_opportunities, behavioral_rules, events_fts (548511c41c39)
- api_keys (a1b2c3d4e5f6)
- Foreign key constraints (e1a2b3c4d5f6)

Auxiliary tables NOT yet under Alembic (separate DB files, tracked for future migration):
- acr_posteriors, trajectories, failure_signatures, skill_variants,
  meta_edits, summaries, improvement_strategies, kg_nodes, kg_edges,
  skills, kb_notes, video_sources, requirements, misalignment_journal
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0re_5ch3m4_v1'
down_revision: Union[str, None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── flow_checkpoints ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS flow_checkpoints (
            session_id TEXT PRIMARY KEY,
            flow_type TEXT NOT NULL,
            state_name TEXT NOT NULL,
            checkpoint_data TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # ── gateway_sessions ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS gateway_sessions (
            session_id TEXT PRIMARY KEY,
            gateway_type TEXT NOT NULL,
            platform_user_id TEXT NOT NULL,
            platform_chat_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            context TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gateway_sessions_platform
        ON gateway_sessions(gateway_type, platform_user_id)
    """)

    # ── jobs (scheduler) ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            callable_name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_config TEXT NOT NULL DEFAULT '{}',
            description TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run_at TEXT,
            next_run_at TEXT,
            run_count INTEGER NOT NULL DEFAULT 0,
            last_result TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flow_checkpoints")
    op.execute("DROP TABLE IF EXISTS gateway_sessions")
    op.execute("DROP TABLE IF EXISTS jobs")
