"""Cross-process cancel requests for running flows (F77).

`flow cancel` used to reach only tasks in its own process. A request is now a
marker file named after the session; PlanActFlow checks it on every iteration
and stops. A file, not a DB field: the running process saves its in-memory
session, which would overwrite a status written by another process.

A marker holds the time of the request. A run ignores markers older than its own start:
a cancel filed while nothing ran the session (a WAITING one) would otherwise stop the
next run, after the user had asked for it again.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

_DIR = Path.home() / ".weebot" / "cancel"


def _marker(session_id: str) -> Path:
    # Hashed so an odd id ("../x") cannot name a path outside the folder.
    return _DIR / hashlib.sha256(session_id.encode()).hexdigest()


def request(session_id: str) -> None:
    """Ask the process running *session_id* to stop."""
    _DIR.mkdir(parents=True, exist_ok=True)
    _marker(session_id).write_text(repr(time.time()), encoding="utf-8")


def take(session_id: str, since: float = 0.0) -> bool:
    """True once if a cancel was requested for *session_id* at or after *since*.

    The marker is consumed either way, so an older one does not stop a later run.
    A marker without a readable time (the old format) counts as older than any *since*.
    """
    marker = _marker(session_id)
    try:
        text = marker.read_text(encoding="utf-8")
        marker.unlink()
    except FileNotFoundError:
        return False
    try:
        requested = float(text)
    except ValueError:
        requested = 0.0
    return requested >= since
