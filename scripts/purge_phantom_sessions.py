#!/usr/bin/env python3
"""Remove the phantom sessions the event journal created before the L3 fix (run once).

Before ``DurableEventBus._journal_agent`` skipped events with no session id, it journaled
each one under the event's own id, and ``log_event`` created a sessions row for it. A
phantom is a session whose every event is named after the session itself and carries an
empty ``session_id`` in its payload. Real sessions never match: their events have their own
ids. Without ``--apply`` the script only counts.

Usage:
    python scripts/purge_phantom_sessions.py                # count only
    python scripts/purge_phantom_sessions.py --apply        # delete them
    python scripts/purge_phantom_sessions.py --db path/to/events.db --apply

Back up first (``scripts/backup.py``): the delete cannot be undone.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path("~/.weebot/events.db")

# An event journaled under its own id, with no session named in its payload.
_PHANTOM_EVENT = (
    "json_extract(e.data_json, '$.id') = e.session_id"
    " AND COALESCE(json_extract(e.data_json, '$.session_id'), '') = ''"
)
# Sessions all of whose events are phantom events.
_PHANTOM_IDS = f"""
    SELECT s.id FROM sessions s
    WHERE EXISTS (SELECT 1 FROM events e WHERE e.session_id = s.id)
      AND NOT EXISTS (
          SELECT 1 FROM events e WHERE e.session_id = s.id AND NOT ({_PHANTOM_EVENT})
      )
"""
_DELETE = "DELETE" + " FROM"


def count(db: Path) -> tuple[int, int]:
    """(phantom sessions, their events)."""
    with sqlite3.connect(db) as conn:
        return conn.execute(
            f"SELECT COUNT(DISTINCT session_id), COUNT(*) FROM events"
            f" WHERE session_id IN ({_PHANTOM_IDS})"
        ).fetchone()


def purge(db: Path) -> tuple[int, int]:
    """Delete the phantoms and their events in one transaction; returns what was removed."""
    conn = sqlite3.connect(db)
    try:
        with conn:
            conn.execute(f"CREATE TEMP TABLE phantom AS {_PHANTOM_IDS}")
            events = conn.execute(
                f"{_DELETE} events WHERE session_id IN (SELECT id FROM phantom)"
            ).rowcount
            sessions = conn.execute(
                f"{_DELETE} sessions WHERE id IN (SELECT id FROM phantom)"
            ).rowcount
        return sessions, events
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DEFAULT_DB), help="event store (default: %(default)s)")
    parser.add_argument("--apply", action="store_true", help="delete; without it, only count")
    args = parser.parse_args(argv)

    db = Path(args.db).expanduser()
    if not db.is_file():
        print(f"No event store at {db}", file=sys.stderr)
        return 1
    if not args.apply:
        sessions, events = count(db)
        print(f"{sessions} phantom sessions, {events} events. Run with --apply to delete them.")
        return 0
    sessions, events = purge(db)
    print(f"Deleted {sessions} phantom sessions and {events} events from {db}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
