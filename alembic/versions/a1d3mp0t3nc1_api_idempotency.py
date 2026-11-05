"""Remember the run an Idempotency-Key started (H12b).

Revision ID: a1d3mp0t3nc1
Revises: f2c0mm1t0001
Create Date: 2026-11-05

The OpenAI-compatible API returns the same run for a repeated key. Rows older than 24 h are
deleted when the key is looked up. The store creates the same table on first use, for
databases that never run alembic.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy import inspect

revision: str = "a1d3mp0t3nc1"
down_revision: Union[str, Sequence[str], None] = "f2c0mm1t0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "api_idempotency" in inspect(op.get_bind()).get_table_names():
        return
    op.execute(
        "CREATE TABLE api_idempotency ("
        "key TEXT NOT NULL, principal TEXT NOT NULL, run_id TEXT NOT NULL, "
        "created_at TEXT NOT NULL, PRIMARY KEY (key, principal))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_idempotency")
