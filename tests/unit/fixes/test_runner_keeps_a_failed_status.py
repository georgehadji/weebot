"""AgentRunner keeps a FAILED session FAILED when the flow returns.

The runner turned every session that was not COMPLETED into WAITING, so a run
that failed or was cancelled (`flow cancel`) was listed as waiting for input.
"""

from __future__ import annotations

from weebot.domain.models.session import Session, SessionStatus
from weebot.interfaces.cli.agent_runner import settled_status


def _s(status):
    return Session(id="s", task="t").set_status(status)


def test_failed_stays_failed():
    assert settled_status(_s(SessionStatus.FAILED)).status == SessionStatus.FAILED


def test_completed_and_waiting_unchanged_and_running_waits():
    assert settled_status(_s(SessionStatus.COMPLETED)).status == SessionStatus.COMPLETED
    assert settled_status(_s(SessionStatus.WAITING)).status == SessionStatus.WAITING
    assert settled_status(_s(SessionStatus.RUNNING)).status == SessionStatus.WAITING
