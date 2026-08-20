"""Merge the api_keys and core-schema-consolidation heads.

Revision ID: b0b1merge0001
Revises: a1b2c3d4e5f6, c0re_5ch3m4_v1
Create Date: 2026-08-04

Both ``a1b2c3d4e5f6`` (add api_keys table) and ``c0re_5ch3m4_v1``
(consolidate core schema) branch off ``e1a2b3c4d5f6``, leaving the
migration graph with two heads. ``alembic upgrade head`` is then
ambiguous and aborts with:

    Multiple head revisions are present for given argument 'head'

which crashed the API container on startup (docker-entrypoint.sh runs
``alembic upgrade head`` before exec'ing uvicorn).

The two branches touch disjoint tables and neither depends on the
other's changes, so this is a pure graph merge: no schema operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

revision: str = "b0b1merge0001"
down_revision: Union[str, Sequence[str], None] = ("a1b2c3d4e5f6", "c0re_5ch3m4_v1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — this revision exists only to rejoin the two branches."""


def downgrade() -> None:
    """No-op — reverting simply re-exposes the two independent heads."""
