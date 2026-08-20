"""Add api_keys table for multi-principal authentication (WI-11).

Revision ID: a1b2c3d4e5f6
Revises: e1a2b3c4d5f6
Create Date: 2026-07-29

This migration adds the ``api_keys`` table for the per-principal credential
store (WI-11). Two hashes are stored:

- ``lookup_hash`` — SHA-256 (deterministic, indexed, fast lookup)
- ``key_hash`` — scrypt + random salt (verification, brute-force resistant)

The raw API key is never persisted.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import alembic.op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    alembic.op.create_table(
        "api_keys",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("principal_id", sa.Text(), nullable=False, index=True),
        sa.Column("lookup_hash", sa.Text(), nullable=False, index=True),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("salt", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    alembic.op.drop_table("api_keys")
