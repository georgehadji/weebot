"""Tests for Enhancement 5 — MisalignmentJournal."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from weebot.domain.models.misalignment_entry import MisalignmentEntry
from weebot.infrastructure.persistence.sqlite_misalignment_journal import SQLiteMisalignmentJournal


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_misalignment.db")


class TestMisalignmentEntry:
    def test_model_fields(self):
        entry = MisalignmentEntry(
            session_id="s1",
            project_path="/tmp/myproject",
            symptom="constraint_violation",
            constraint_text="do not delete",
            step_description="Delete files",
        )
        assert entry.id  # auto-generated
        assert entry.created_at is not None
        assert entry.symptom == "constraint_violation"

    def test_defaults(self):
        entry = MisalignmentEntry()
        assert entry.session_id == ""
        assert entry.constraint_text is None
        assert entry.correction_text is None


class TestSQLiteMisalignmentJournal:
    @pytest.mark.asyncio
    async def test_record_and_retrieve(self, db_path):
        j = SQLiteMisalignmentJournal(db_path)
        entry = MisalignmentEntry(
            session_id="s1",
            project_path="/proj",
            symptom="constraint_violation",
            constraint_text="do not delete",
        )
        await j.record(entry)
        results = await j.get_recent("/proj", 5)
        assert len(results) == 1
        assert results[0].symptom == "constraint_violation"
        assert results[0].constraint_text == "do not delete"

    @pytest.mark.asyncio
    async def test_project_path_scoping(self, db_path):
        j = SQLiteMisalignmentJournal(db_path)
        await j.record(MisalignmentEntry(project_path="/projA", symptom="constraint_violation"))
        await j.record(MisalignmentEntry(project_path="/projB", symptom="user_correction"))
        results_a = await j.get_recent("/projA", 5)
        results_b = await j.get_recent("/projB", 5)
        assert len(results_a) == 1 and results_a[0].symptom == "constraint_violation"
        assert len(results_b) == 1 and results_b[0].symptom == "user_correction"

    @pytest.mark.asyncio
    async def test_limit_respected(self, db_path):
        j = SQLiteMisalignmentJournal(db_path)
        for i in range(10):
            await j.record(MisalignmentEntry(
                project_path="/proj", symptom="constraint_violation",
                step_description=f"step {i}"
            ))
        results = await j.get_recent("/proj", 3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_record_failure_does_not_raise(self):
        j = SQLiteMisalignmentJournal("/nonexistent/path/test.db")
        # Should swallow the exception, not raise
        await j.record(MisalignmentEntry(symptom="constraint_violation"))

    @pytest.mark.asyncio
    async def test_get_recent_failure_returns_empty(self):
        j = SQLiteMisalignmentJournal("/nonexistent/path/test.db")
        results = await j.get_recent("/proj", 5)
        assert results == []

    @pytest.mark.asyncio
    async def test_newest_first_ordering(self, db_path):
        j = SQLiteMisalignmentJournal(db_path)
        await j.record(MisalignmentEntry(
            project_path="/proj", symptom="constraint_violation",
            step_description="first"
        ))
        await j.record(MisalignmentEntry(
            project_path="/proj", symptom="user_correction",
            step_description="second"
        ))
        results = await j.get_recent("/proj", 5)
        assert results[0].step_description == "second"  # newest first
