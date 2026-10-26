"""MetaAnalysisState wrote session.meta_notes; planning never read them back."""

from __future__ import annotations

from weebot.domain.services.session_lessons import session_lessons
from weebot.domain.models.session import Session


def test_notes_written_by_meta_analysis_come_back_as_planner_lines():
    session = Session(id="s", user_id="u", agent_id="a").add_meta_note("Check the path exists first")
    lines = session_lessons(session.context.meta_notes)
    assert lines == ["Lesson from an earlier task in this session: Check the path exists first"]


def test_blank_notes_are_dropped_and_none_means_nothing():
    assert session_lessons(["", "  "]) == []
    assert session_lessons([]) == []
