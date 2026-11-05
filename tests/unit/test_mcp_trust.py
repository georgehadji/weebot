"""H12: per-server MCP trust, the typed config, and sse headers."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager

import pytest

from weebot.application.services.tool_guards import is_outbound_tool, reads_only
from weebot.core import mcp_trust
from weebot.domain.models.mcp import MCPServerConfig
from weebot.infrastructure.mcp import mcp_client_manager as mod


@pytest.fixture(autouse=True)
def _clean_registry():
    mcp_trust._UNTRUSTED.clear()
    yield
    mcp_trust._UNTRUSTED.clear()


def test_a_server_is_untrusted_unless_its_config_says_otherwise():
    assert MCPServerConfig(name="a", command="x").trust == "untrusted"
    assert MCPServerConfig(name="a", command="x", trust="trusted").trust == "trusted"


def test_every_tool_of_an_untrusted_server_asks_even_one_named_like_a_read():
    mcp_trust.register_server("jira", "untrusted")

    assert is_outbound_tool("mcp__jira__jira_get_issue")
    assert not reads_only("mcp__jira__jira_get_issue", {})


def test_a_trusted_server_keeps_the_name_heuristic():
    mcp_trust.register_server("jira", "trusted")

    assert not is_outbound_tool("mcp__jira__jira_get_issue")
    assert is_outbound_tool("mcp__jira__jira_create_issue")


def test_a_server_nobody_registered_keeps_the_name_heuristic():
    assert not is_outbound_tool("mcp__unknown__get_thing")


def test_trust_is_matched_on_the_sanitised_server_name():
    mcp_trust.register_server("x-docs", "untrusted")

    assert is_outbound_tool("mcp__x_docs__get_page")


@pytest.mark.asyncio
async def test_connecting_registers_the_trust_and_cleanup_removes_it(monkeypatch):
    def refuse(params):
        raise RuntimeError("stop")

    monkeypatch.setattr(mod, "stdio_client", refuse)
    mgr = mod.MCPClientManager({})
    async with AsyncExitStack() as stack:
        with pytest.raises(RuntimeError):
            await mgr._connect_server("jira", {"command": "x"}, stack)
    assert is_outbound_tool("mcp__jira__jira_get_issue")  # no "trust" key: untrusted

    await mgr.cleanup()
    assert not is_outbound_tool("mcp__jira__jira_get_issue")


@pytest.mark.asyncio
async def test_a_trusted_config_registers_as_trusted(monkeypatch):
    monkeypatch.setattr(mod, "stdio_client", lambda params: (_ for _ in ()).throw(RuntimeError()))
    mgr = mod.MCPClientManager({})
    async with AsyncExitStack() as stack:
        with pytest.raises(RuntimeError):
            await mgr._connect_server("jira", {"command": "x", "trust": "trusted"}, stack)

    assert not is_outbound_tool("mcp__jira__jira_get_issue")


@pytest.mark.asyncio
async def test_sse_sends_the_headers_and_the_bearer_token(monkeypatch):
    captured = {}

    @asynccontextmanager
    async def fake_sse(url, headers=None):
        captured.update(url=url, headers=headers)
        raise RuntimeError("stop")
        yield  # pragma: no cover

    monkeypatch.setattr(mod, "sse_client", fake_sse)
    config = MCPServerConfig(
        name="s", transport="sse", url="https://h/sse", headers={"X-Team": "a"},
        auth={"type": "bearer", "token": "tok"},
    )
    async with AsyncExitStack() as stack:
        with pytest.raises(RuntimeError):
            await mod.MCPClientManager({})._connect_sse(config, stack)

    assert captured["headers"] == {"X-Team": "a", "Authorization": "Bearer tok"}


@pytest.mark.asyncio
async def test_an_entry_the_typed_config_rejects_fails_that_server():
    async with AsyncExitStack() as stack:
        with pytest.raises(ValueError):
            await mod.MCPClientManager({})._connect_server("s", {"transport": "carrier-pigeon"}, stack)
