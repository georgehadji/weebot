"""Tests for KnowledgeTool (SQLite FTS5 persistent knowledge base)."""
from __future__ import annotations

import json
import pytest

from weebot.tools.knowledge_tool import KnowledgeTool


@pytest.fixture
def kb(tmp_path):
    """Fresh KnowledgeTool backed by a temp-file SQLite database."""
    return KnowledgeTool(db_path=str(tmp_path / "kb_test.db"))


# ---------------------------------------------------------------------------
# add_note
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_note_returns_note_id(kb):
    result = await kb.execute(action="add_note", title="Auth approach", body="Use JWT tokens")
    assert not result.is_error
    data = json.loads(result.output)
    assert "note_id" in data
    assert data["title"] == "Auth approach"


@pytest.mark.asyncio
async def test_add_note_missing_title_is_error(kb):
    result = await kb.execute(action="add_note", body="some content")
    assert result.is_error
    assert "title" in result.error


@pytest.mark.asyncio
async def test_add_note_missing_body_is_error(kb):
    result = await kb.execute(action="add_note", title="My note")
    assert result.is_error
    assert "body" in result.error


@pytest.mark.asyncio
async def test_add_note_with_tags_and_project(kb):
    result = await kb.execute(
        action="add_note",
        title="DB schema",
        body="Users table has id, email, created_at",
        tags="database, schema",
        project_id="proj-1",
    )
    assert not result.is_error


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_finds_added_note(kb):
    await kb.execute(action="add_note", title="JWT authentication", body="Use HS256 algorithm")
    result = await kb.execute(action="search", query="authentication")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["count"] >= 1
    assert any("JWT" in r["title"] for r in data["results"])


@pytest.mark.asyncio
async def test_search_missing_query_is_error(kb):
    result = await kb.execute(action="search")
    assert result.is_error
    assert "query" in result.error


@pytest.mark.asyncio
async def test_search_empty_query_is_error(kb):
    result = await kb.execute(action="search", query="   ")
    assert result.is_error


@pytest.mark.asyncio
async def test_search_no_results_returns_empty_list(kb):
    result = await kb.execute(action="search", query="xyzzyquux")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["count"] == 0


# ---------------------------------------------------------------------------
# get_note
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_note_returns_full_note(kb):
    add = await kb.execute(action="add_note", title="DB design", body="Use Postgres")
    note_id = json.loads(add.output)["note_id"]

    result = await kb.execute(action="get_note", note_id=note_id)
    assert not result.is_error
    data = json.loads(result.output)
    assert data["title"] == "DB design"
    assert data["body"] == "Use Postgres"


@pytest.mark.asyncio
async def test_get_note_unknown_id_is_error(kb):
    result = await kb.execute(action="get_note", note_id="notexist")
    assert result.is_error
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_get_note_missing_id_is_error(kb):
    result = await kb.execute(action="get_note")
    assert result.is_error
    assert "note_id" in result.error


# ---------------------------------------------------------------------------
# list_notes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_notes_returns_all(kb):
    await kb.execute(action="add_note", title="Note A", body="Content A")
    await kb.execute(action="add_note", title="Note B", body="Content B")
    result = await kb.execute(action="list_notes")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_list_notes_filtered_by_project(kb):
    await kb.execute(action="add_note", title="P1 note", body="body", project_id="proj-1")
    await kb.execute(action="add_note", title="P2 note", body="body", project_id="proj-2")
    result = await kb.execute(action="list_notes", project_id="proj-1")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["count"] == 1
    assert data["notes"][0]["title"] == "P1 note"


# ---------------------------------------------------------------------------
# delete_note
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_note_removes_it(kb):
    add = await kb.execute(action="add_note", title="Temp", body="delete me")
    note_id = json.loads(add.output)["note_id"]

    del_result = await kb.execute(action="delete_note", note_id=note_id)
    assert not del_result.is_error

    get_result = await kb.execute(action="get_note", note_id=note_id)
    assert get_result.is_error  # gone


@pytest.mark.asyncio
async def test_delete_note_missing_id_is_error(kb):
    result = await kb.execute(action="delete_note")
    assert result.is_error
    assert "note_id" in result.error


# ---------------------------------------------------------------------------
# unknown action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action_is_error(kb):
    result = await kb.execute(action="fly_to_moon")
    assert result.is_error
    assert "Unknown action" in result.error
