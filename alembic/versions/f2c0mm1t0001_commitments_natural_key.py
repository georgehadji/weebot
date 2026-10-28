"""One row per promise: collapse duplicate commitments and add a unique natural key.

Revision ID: f2c0mm1t0001
Revises: b0b1merge0001
Create Date: 2026-10-28

Commitments were saved under a fresh uuid4 on every ``save_session`` (audit A12), so
one promise could fill many rows. The ids are deterministic now; this removes the
rows left from before and adds the index that stops new repeats. Per key it keeps
the row whose status moved past ``pending`` if there is one, else the oldest. The
same statements run at repository start-up (``sqlite_state_repo.py``), for databases
that never run alembic. Back up the database before upgrading: deleted rows do not
come back on downgrade.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy import inspect

revision: str = "f2c0mm1t0001"
down_revision: Union[str, Sequence[str], None] = "b0b1merge0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEDUP = """
DELETE FROM commitments WHERE rowid NOT IN (
    SELECT rowid FROM (
        SELECT rowid, ROW_NUMBER() OVER (
            PARTITION BY source_session_id, COALESCE(source_event_id, ''), promise_text
            ORDER BY status = 'pending', created_at, rowid
        ) AS rank FROM commitments
    ) WHERE rank = 1
)
"""


def upgrade() -> None:
    if "commitments" not in inspect(op.get_bind()).get_table_names():
        return  # the repository creates the table, with the index, on first start
    op.execute(_DEDUP)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_commitments_natural_key "
        "ON commitments(source_session_id, source_event_id, promise_text)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_commitments_natural_key")
