"""The CLI prints a line a person can read for every event type.

Found on the 2026-10-23 smoke run: each CoVe check printed as a raw pydantic
repr (`type='verification' id='27de...' timestamp=datetime.datetime(...)`),
because `_format_event` fell back to `str(event)` for any type it did not list.
"""

from __future__ import annotations

from weebot.domain.models.event import TrajectoryDiagnosisEvent, VerificationEvent
from weebot.interfaces.cli.event_logger import _format_event


def test_a_verification_check_reads_as_one_line():
    line = _format_event(
        VerificationEvent(question="What was the result?", answer="391", consistent=True)
    )
    assert "What was the result?" in line and "timestamp" not in line


def test_an_unlisted_event_prints_its_type_not_its_repr():
    line = _format_event(TrajectoryDiagnosisEvent())
    assert "timestamp" not in line and "trajectory" in line.lower()
