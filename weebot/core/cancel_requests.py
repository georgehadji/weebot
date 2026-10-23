"""Cross-process cancel requests for running flows (F77).

`flow cancel` used to reach only tasks in its own process. A request is now a
marker file named after the session; PlanActFlow checks it on every iteration
and stops. A file, not a DB field: the running process saves its in-memory
session, which would overwrite a status written by another process.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_DIR = Path.home() / ".weebot" / "cancel"


def _marker(session_id: str) -> Path:
    # Hashed so an odd id ("../x") cannot name a path outside the folder.
    return _DIR / hashlib.sha256(session_id.encode()).hexdigest()


def request(session_id: str) -> None:
    """Ask the process running *session_id* to stop."""
    _DIR.mkdir(parents=True, exist_ok=True)
    _marker(session_id).write_text(session_id, encoding="utf-8")


def take(session_id: str) -> bool:
    """True once if a cancel was requested for *session_id* (the request is consumed)."""
    marker = _marker(session_id)
    try:
        marker.unlink()
    except FileNotFoundError:
        return False
    return True
