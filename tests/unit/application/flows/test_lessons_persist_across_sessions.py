"""A lesson filed by one session reaches the planner of a later session of the same project."""

import os

import pytest

from weebot.domain.models.misalignment_entry import MisalignmentEntry
from weebot.domain.services.session_lessons import journal_lessons, project_key
from weebot.infrastructure.persistence.sqlite_misalignment_journal import SQLiteMisalignmentJournal


def test_project_key_prefers_working_dir():
    assert project_key("/a") == "/a"
    assert project_key(None) == os.getcwd()


def test_journal_lessons_skips_other_symptoms_and_known_notes():
    entries = [
        MisalignmentEntry(symptom="session_lesson", correction_text="use rg"),
        MisalignmentEntry(symptom="session_lesson", correction_text="already known"),
        MisalignmentEntry(symptom="user_correction", correction_text="no"),
    ]
    out = journal_lessons(entries, ["already known"])
    assert out == ["Lesson from an earlier session of this project: use rg"]


@pytest.mark.asyncio
async def test_lesson_round_trips_per_project(tmp_path):
    j = SQLiteMisalignmentJournal(tmp_path / "j.db")
    await j.record(MisalignmentEntry(project_path="/p1", symptom="session_lesson", correction_text="x"))
    assert len(await j.get_recent("/p1")) == 1
    assert await j.get_recent("/p2") == []
