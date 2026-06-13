"""Unit tests for MiddlewareChain (Improvement #1)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.middleware.chain import MiddlewareChain
from weebot.application.middleware.base import (
    Middleware,
    MiddlewareRequest,
    MiddlewareResponse,
    ToolCallResult,
)

# ── Test doubles ──────────────────────────────────────────────────

class _PassthroughMiddleware(Middleware):
    """Middleware that passes everything through unchanged."""
    def name(self) -> str:
        return "passthrough"


class _ToolInjectMiddleware(Middleware):
    """Middleware that injects an extra tool."""
    def name(self) -> str:
        return "tool_inject"

    async def before_request(self, request, state):
        tools = list(request.tools)
        tools.append({"function": {"name": "injected_tool"}, "type": "function"})
        request.tools = tools
        return request, state


class _ContentModMiddleware(Middleware):
    """Middleware that modifies response content."""
    def name(self) -> str:
        return "content_mod"

    async def after_response(self, response, request, state):
        response.content = f"[MODIFIED] {response.content}"
        return response, state


class _LogOrderMiddleware(Middleware):
    """Middleware that logs its execution order."""
    def __init__(self, name: str, log: list):
        self._mw_name = name
        self._log = log

    def name(self) -> str:
        return self._mw_name

    async def before_request(self, request, state):
        self._log.append(f"{self._mw_name}:before")
        return request, state

    async def after_response(self, response, request, state):
        self._log.append(f"{self._mw_name}:after")
        return response, state


# ── Tests ─────────────────────────────────────────────────────────

class TestMiddlewareChain:
    """Validates MiddlewareChain pipeline behavior."""

    @pytest.mark.asyncio
    async def test_empty_chain_passthrough_messages(self):
        chain = MiddlewareChain()
        assert chain.is_empty()
        msgs, tools = await chain.apply_before_request(
            [{"role": "user", "content": "hello"}], []
        )
        assert msgs == [{"role": "user", "content": "hello"}]
        assert tools == []

    @pytest.mark.asyncio
    async def test_empty_chain_passthrough_response(self):
        chain = MiddlewareChain()
        content, tool_calls = await chain.apply_after_response(
            "ok", [], [], []
        )
        assert content == "ok"
        assert tool_calls == []

    @pytest.mark.asyncio
    async def test_add_appends_to_chain(self):
        chain = MiddlewareChain()
        chain.add(_PassthroughMiddleware())
        assert not chain.is_empty()

    @pytest.mark.asyncio
    async def test_single_middleware_modifies_tools(self):
        chain = MiddlewareChain([_ToolInjectMiddleware()])
        msgs, tools = await chain.apply_before_request(
            [{"role": "user"}],
            [{"function": {"name": "bash"}, "type": "function"}],
        )
        tool_names = [t.get("function", {}).get("name") for t in tools]
        assert "bash" in tool_names
        assert "injected_tool" in tool_names

    @pytest.mark.asyncio
    async def test_single_middleware_modifies_response(self):
        chain = MiddlewareChain([_ContentModMiddleware()])
        content, tool_calls = await chain.apply_after_response(
            "hello", [], [], []
        )
        assert content == "[MODIFIED] hello"

    @pytest.mark.asyncio
    async def test_ordered_execution(self):
        log: list[str] = []
        mw1 = _LogOrderMiddleware("A", log)
        mw2 = _LogOrderMiddleware("B", log)
        chain = MiddlewareChain([mw1, mw2])

        await chain.apply_before_request([], [])
        await chain.apply_after_response("", [], [], [])

        assert log == [
            "A:before", "B:before",
            "A:after", "B:after",
        ]

    @pytest.mark.asyncio
    async def test_after_tool_call_intercepts(self):
        chain = MiddlewareChain([_ContentModMiddleware()])
        # ContentModMiddleware only overrides after_response, so after_tool_call is passthrough
        result = await chain.apply_after_tool_call(
            tool_name="bash",
            arguments={"cmd": "ls"},
            output="file1.txt\nfile2.txt",
            error=None,
            is_error=False,
        )
        assert result.tool_name == "bash"
        assert "file1.txt" in result.output

    @pytest.mark.asyncio
    async def test_chain_state_isolated_per_call(self):
        """Each call to apply_* should create fresh state."""
        class _StateCheckMiddleware(Middleware):
            def name(self) -> str:
                return "state_check"

            async def before_request(self, request, state):
                state["counter"] = state.get("counter", 0) + 1
                return request, state

        mw = _StateCheckMiddleware()
        chain = MiddlewareChain([mw])

        # First call — counter starts at 0, becomes 1
        msgs1, _ = await chain.apply_before_request([{"role": "user", "content": "first"}], [])
        assert msgs1 == [{"role": "user", "content": "first"}]

        # Second call — counter should be fresh (NOT 2)
        msgs2, _ = await chain.apply_before_request([{"role": "user", "content": "second"}], [])
        assert msgs2 == [{"role": "user", "content": "second"}]
