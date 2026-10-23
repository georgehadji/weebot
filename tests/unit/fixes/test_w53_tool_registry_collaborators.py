"""W5.3 (F28): the tool registry gets its collaborators from the caller.

`create_tool_collection_from_names` built a fresh `Container()` for every tool
with `set_rerank` (web search, research engine), for the state-repo tools, and
for a missing flow factory: several whole object graphs per collection. It now
takes `state_repo` and `rerank` as arguments, and the callers that hold a
container pass theirs.
"""

from __future__ import annotations

import pytest

from weebot.tools.tool_registry import RoleBasedToolRegistry


@pytest.fixture
def no_container(monkeypatch):
    built: list[bool] = []

    def _record(*a, **k):
        built.append(True)
        raise AssertionError("the registry built a Container")

    monkeypatch.setattr("weebot.application.di.Container", _record)
    return built


def test_a_rerank_tool_gets_the_reranker_it_is_given(no_container):
    rerank = object()
    tools = RoleBasedToolRegistry().create_tool_collection_from_names(
        ["web_search"], rerank=rerank
    )
    assert tools.get_tool("web_search")._rerank is rerank and no_container == []


def test_a_state_tool_gets_the_state_repo_it_is_given(no_container):
    repo = object()
    tools = RoleBasedToolRegistry().create_tool_collection_from_names(
        ["dispatch_parallel_tasks"], state_repo=repo, flow_factory=lambda s: None
    )
    assert tools.get_tool("dispatch_parallel_tasks")._state_repo is repo
    assert no_container == []


def test_no_flow_factory_builds_no_container(no_container):
    RoleBasedToolRegistry().create_tool_collection_from_names(["debate"])
    assert no_container == []


async def test_build_tools_uses_the_container_registry(monkeypatch):
    """W5.5 replaced the per-call state_repo/rerank arguments with the wiring
    the container's tool_registry carries; build_tools must use that registry."""
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.interfaces import factories

    used = []

    class _Registry:
        def create_tool_collection(self, role, **kw):
            used.append(role)
            return ToolCollection()

    real = factories._cached
    monkeypatch.setattr(
        factories, "_cached", lambda k: _Registry() if k == "tool_registry" else real(k)
    )

    async def _no_mcp():
        return []

    monkeypatch.setattr(factories, "_configured_mcp_tools", _no_mcp)
    await factories.build_tools(role="researcher")
    assert used == ["researcher"]
