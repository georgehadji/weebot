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


# ── H12: sampling through the manager ──────────────────────────────────────────────────────


class _Handler:
    def __init__(self):
        self.seen = []

    async def handle_sampling(self, server, request, policy, *, session_id=None, tainted=False):
        from weebot.application.services.mcp_sampling_handler import SamplingResult

        self.seen.append((server, session_id, tainted, request.max_tokens))
        return SamplingResult(content=[{"type": "text", "text": "hi"}], model="m")


def _params(max_tokens=50):
    from mcp.types import CreateMessageRequestParams, SamplingMessage, TextContent

    return CreateMessageRequestParams(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text="q"))],
        maxTokens=max_tokens,
    )


@pytest.mark.asyncio
async def test_a_sampling_request_uses_the_session_of_the_tool_call_in_flight():
    from weebot.domain.models.mcp import MCPSamplingPolicy
    from weebot.application.ports.mcp_sampling_port import CallContext
    from weebot.infrastructure.mcp.session_callbacks import make_sampling_callback

    handler = _Handler()
    flight = [CallContext("s1", True)]
    callback = make_sampling_callback(
        "srv", MCPSamplingPolicy(enabled=True), handler, lambda: flight[-1] if flight else None
    )

    reply = await callback(None, _params())

    assert reply.content.text == "hi" and reply.role == "assistant"
    assert handler.seen == [("srv", "s1", True, 50)]


@pytest.mark.asyncio
async def test_a_sampling_request_with_no_call_in_flight_has_no_session():
    from mcp.types import ErrorData

    from weebot.application.services.mcp_sampling_handler import MCPSamplingHandler
    from weebot.domain.models.mcp import MCPSamplingPolicy
    from weebot.infrastructure.mcp.session_callbacks import make_sampling_callback

    callback = make_sampling_callback(
        "srv", MCPSamplingPolicy(enabled=True), MCPSamplingHandler(llm_provider=object()),
        lambda: None,
    )

    assert isinstance(await callback(None, _params()), ErrorData)


@pytest.mark.asyncio
async def test_the_manager_records_the_call_in_flight_and_clears_it(monkeypatch):
    from weebot.application.ports.mcp_sampling_port import CallContext

    manager = mod.MCPClientManager({}, call_context=lambda: CallContext("s9", True))
    seen = {}

    class Session:
        async def call_tool(self, name, arguments):
            seen["flight"] = list(manager._in_flight["srv"])
            raise RuntimeError("stop")

    manager._clients["srv"] = Session()
    manager._tools_cache["srv"] = [type("T", (), {"name": "get", "description": "", "inputSchema": {}})()]
    with pytest.raises(RuntimeError):
        await manager.call_tool("mcp__srv__get", {})

    assert [(c.session_id, c.tainted) for c in seen["flight"]] == [("s9", True)]
    assert manager._in_flight["srv"] == []


@pytest.mark.asyncio
async def test_a_server_gets_the_callback_only_when_its_policy_enables_sampling(monkeypatch):
    captured = []

    class FakeSession:
        def __init__(self, r, w, sampling_callback=None):
            captured.append(sampling_callback)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            return None

    monkeypatch.setattr(mod, "ClientSession", FakeSession)
    manager = mod.MCPClientManager({}, sampling_handler=_Handler())
    for sampling in ({"enabled": True}, {}):
        config = MCPServerConfig(name="s", command="x", sampling=sampling)
        async with AsyncExitStack() as stack:
            await manager._open_session(config, (None, None), stack)

    assert callable(captured[0]) and captured[1] is None


def test_no_sampling_handler_is_built_while_no_server_enables_sampling():
    from unittest.mock import MagicMock

    from weebot.application.di import Container

    container = MagicMock()
    build = Container._create_mcp_sampling_handler
    assert build(container, {"a": {"command": "x"}, "b": {"sampling": {"enabled": False}}}) is None
    container._create_llm_for_role.assert_not_called()

    handler = build(container, {"a": {"sampling": {"enabled": True}}})
    assert handler is not None
    container._create_llm_for_role.assert_called_once_with("subagent")
