"""Tests for ProductTool (product backlog and PRD generator)."""
from __future__ import annotations

import json
import pytest

from weebot.tools.product_tool import ProductTool


@pytest.fixture
def pt(tmp_path):
    """Fresh ProductTool backed by a temp-file SQLite database."""
    return ProductTool(db_path=str(tmp_path / "product_test.db"))


# ---------------------------------------------------------------------------
# add_requirement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_requirement_returns_req_id(pt):
    result = await pt.execute(
        action="add_requirement",
        project_id="proj-1",
        title="User login",
        description="Users can log in via email + password",
    )
    assert not result.is_error
    data = json.loads(result.output)
    assert "req_id" in data
    assert data["title"] == "User login"


@pytest.mark.asyncio
async def test_add_requirement_missing_project_id_is_error(pt):
    result = await pt.execute(action="add_requirement", title="Something")
    assert result.is_error
    assert "project_id" in result.error


@pytest.mark.asyncio
async def test_add_requirement_missing_title_is_error(pt):
    result = await pt.execute(action="add_requirement", project_id="proj-1")
    assert result.is_error
    assert "title" in result.error


@pytest.mark.asyncio
async def test_add_requirement_invalid_category_is_error(pt):
    result = await pt.execute(
        action="add_requirement",
        project_id="proj-1",
        title="Test",
        category="wishlist",
    )
    assert result.is_error
    assert "category" in result.error.lower() or "Invalid" in result.error


@pytest.mark.asyncio
async def test_add_requirement_default_status_is_draft(pt):
    await pt.execute(action="add_requirement", project_id="p", title="Feature X")
    list_result = await pt.execute(action="list_requirements", project_id="p")
    data = json.loads(list_result.output)
    assert data["requirements"][0]["status"] == "draft"


# ---------------------------------------------------------------------------
# list_requirements
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_requirements_returns_all(pt):
    await pt.execute(action="add_requirement", project_id="p", title="A")
    await pt.execute(action="add_requirement", project_id="p", title="B")
    result = await pt.execute(action="list_requirements", project_id="p")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_list_requirements_filter_by_status(pt):
    await pt.execute(action="add_requirement", project_id="p", title="A")
    req_b = await pt.execute(action="add_requirement", project_id="p", title="B")
    req_id = json.loads(req_b.output)["req_id"]
    await pt.execute(action="update_status", req_id=req_id, status="approved")

    result = await pt.execute(action="list_requirements", project_id="p", status="approved")
    data = json.loads(result.output)
    assert data["count"] == 1
    assert data["requirements"][0]["title"] == "B"


@pytest.mark.asyncio
async def test_list_requirements_sorted_by_priority(pt):
    await pt.execute(action="add_requirement", project_id="p", title="Low", priority=5)
    await pt.execute(action="add_requirement", project_id="p", title="High", priority=1)
    result = await pt.execute(action="list_requirements", project_id="p")
    data = json.loads(result.output)
    titles = [r["title"] for r in data["requirements"]]
    assert titles[0] == "High"  # priority 1 comes first


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_changes_status(pt):
    add = await pt.execute(action="add_requirement", project_id="p", title="Feat")
    req_id = json.loads(add.output)["req_id"]

    result = await pt.execute(action="update_status", req_id=req_id, status="approved")
    assert not result.is_error

    list_r = await pt.execute(action="list_requirements", status="approved")
    data = json.loads(list_r.output)
    assert any(r["req_id"] == req_id for r in data["requirements"])


@pytest.mark.asyncio
async def test_update_status_invalid_status_is_error(pt):
    result = await pt.execute(action="update_status", req_id="abc", status="pending")
    assert result.is_error
    assert "Invalid status" in result.error or "status" in result.error.lower()


@pytest.mark.asyncio
async def test_update_status_unknown_req_id_is_error(pt):
    result = await pt.execute(action="update_status", req_id="nonexistent", status="done")
    assert result.is_error
    assert "not found" in result.error


@pytest.mark.asyncio
async def test_update_status_missing_req_id_is_error(pt):
    result = await pt.execute(action="update_status", status="done")
    assert result.is_error
    assert "req_id" in result.error


# ---------------------------------------------------------------------------
# generate_prd
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_prd_returns_markdown(pt):
    await pt.execute(
        action="add_requirement",
        project_id="proj-1",
        title="Login page",
        description="Allow users to sign in.",
        category="feature",
    )
    result = await pt.execute(action="generate_prd", project_id="proj-1")
    assert not result.is_error
    assert "# Product Requirements Document" in result.output
    assert "proj-1" in result.output
    assert "Login page" in result.output


@pytest.mark.asyncio
async def test_generate_prd_missing_project_id_is_error(pt):
    result = await pt.execute(action="generate_prd")
    assert result.is_error
    assert "project_id" in result.error


@pytest.mark.asyncio
async def test_generate_prd_no_requirements_is_error(pt):
    result = await pt.execute(action="generate_prd", project_id="empty-project")
    assert result.is_error
    assert "No requirements" in result.error


# ---------------------------------------------------------------------------
# get_roadmap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_roadmap_returns_json(pt):
    await pt.execute(action="add_requirement", project_id="p", title="F1", category="feature")
    await pt.execute(action="add_requirement", project_id="p", title="B1", category="bug")
    result = await pt.execute(action="get_roadmap", project_id="p")
    assert not result.is_error
    data = json.loads(result.output)
    assert data["project_id"] == "p"
    assert data["total"] == 2
    assert "feature" in data["by_category"]
    assert "bug" in data["by_category"]


@pytest.mark.asyncio
async def test_get_roadmap_missing_project_id_is_error(pt):
    result = await pt.execute(action="get_roadmap")
    assert result.is_error
    assert "project_id" in result.error


# ---------------------------------------------------------------------------
# unknown action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action_is_error(pt):
    result = await pt.execute(action="launch_rocket")
    assert result.is_error
    assert "Unknown action" in result.error
