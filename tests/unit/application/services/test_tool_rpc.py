"""Code in a persistent kernel calls tools through the host's guards (H17, PR 2)."""

from __future__ import annotations

import asyncio

import pytest

from tests.unit.test_tool_executor_egress import FakeToolCollection, make_guard
from weebot.application.agents.executor._session_scope import get_session_scope
from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.services.tool_approval import AutoApproval, approval_scope
from weebot.application.services.tool_guards import GuardedTool, default_guard_chain
from weebot.application.services.tool_rpc import (
    ToolRpcServer,
    current_dispatch,
    parse_allowed,
)
from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.tool_result import ToolResult
from weebot.infrastructure.sandbox.native_kernel import NativeKernel


def _call(name: str, **arguments) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "call_tool",
        "params": {"name": name, "arguments": arguments},
    }


def _server(dispatch, allowed="bash,web_search", max_calls=24) -> ToolRpcServer:
    return ToolRpcServer(dispatch, parse_allowed(allowed), max_calls)


async def _echo(name, arguments):
    return ToolResult(output=f"{name}:{arguments}")


class TestServer:
    @pytest.mark.asyncio
    async def test_a_call_returns_the_tools_output(self):
        reply = await _server(_echo).handle(_call("bash", command="ls"))
        assert reply["result"]["output"] == "bash:{'command': 'ls'}"

    @pytest.mark.asyncio
    async def test_a_tool_off_the_list_is_refused(self):
        reply = await _server(_echo, "bash").handle(_call("web_search", query="x"))
        assert "not available" in reply["error"]["message"]

    @pytest.mark.asyncio
    async def test_dispatch_tools_are_never_allowed(self):
        assert "python_execute" not in parse_allowed("python_execute,dispatch_parallel_tasks,bash")
        forced = ToolRpcServer(_echo, frozenset({"python_execute"}))
        assert "error" in await forced.handle(_call("python_execute", code="1"))

    @pytest.mark.asyncio
    async def test_the_call_cap_holds(self):
        server = _server(_echo, max_calls=2)
        for _ in range(2):
            assert "result" in await server.handle(_call("bash", command="x"))
        assert "At most 2" in (await server.handle(_call("bash", command="x")))["error"]["message"]

    @pytest.mark.asyncio
    async def test_a_malformed_frame_is_an_error_not_a_crash(self):
        server = _server(_echo)
        assert "error" in await server.handle({"id": 3, "method": "nope"})
        assert "error" in await server.handle({"id": 4, "method": "call_tool", "params": []})

    @pytest.mark.asyncio
    async def test_a_pause_for_approval_becomes_an_error_for_the_code(self):
        async def paused(name, arguments):
            return ToolResult(output="", data={"approval_required": {"reason": "x"}})

        reply = await _server(paused).handle(_call("bash", command="x"))
        assert "needs approval" in reply["result"]["error"]

    @pytest.mark.asyncio
    async def test_a_dispatch_that_raises_is_an_error_reply(self):
        async def boom(name, arguments):
            raise ValueError("secret detail")

        reply = await _server(boom).handle(_call("bash", command="x"))
        assert reply["result"]["error"] == "The tool call failed: ValueError"


@pytest.fixture
def kernel():
    backend = NativeKernel()
    handles = []

    class _Box:
        async def start(self, session="s"):
            handle = await backend.start(session)
            handles.append(handle)
            return handle

        exec = staticmethod(backend.exec)

    yield _Box()
    for handle in handles:
        asyncio.run(backend.stop(handle))


class TestInTheKernel:
    @pytest.mark.asyncio
    async def test_code_calls_a_tool_and_state_survives(self, kernel):
        handle = await kernel.start()
        server = _server(_echo)

        await kernel.exec(handle, "import weebot_tools\nx = 5", 10, server.handle)
        result = await kernel.exec(handle, "print(x, weebot_tools.bash('ls'))", 10, server.handle)

        assert result.success, result.error
        assert result.stdout == "5 bash:{'command': 'ls'}\n"

    @pytest.mark.asyncio
    async def test_a_refused_call_raises_tool_error_in_the_code(self, kernel):
        handle = await kernel.start()
        code = (
            "import weebot_tools\n"
            "try:\n    weebot_tools.call_tool('python_execute', code='1')\n"
            "except weebot_tools.ToolError as e:\n    print('refused:', e)\n"
        )
        result = await kernel.exec(handle, code, 10, _server(_echo).handle)
        assert result.stdout.startswith("refused:") and "not available" in result.stdout

    @pytest.mark.asyncio
    async def test_without_a_handler_a_call_is_an_error_and_the_kernel_lives(self, kernel):
        handle = await kernel.start()
        code = (
            "import weebot_tools\n"
            "try:\n    weebot_tools.bash('ls')\nexcept weebot_tools.ToolError as e:\n"
            "    print('off:', e)\n"
        )
        result = await kernel.exec(handle, code, 10)
        after = await kernel.exec(handle, "print(1 + 1)", 10)
        assert "off: Tool calls are not available" in result.stdout
        assert after.stdout == "2\n"

    @pytest.mark.asyncio
    async def test_time_in_a_tool_does_not_count_against_the_timeout(self, kernel):
        handle = await kernel.start()

        async def slow(name, arguments):
            await asyncio.sleep(1.5)
            return ToolResult(output="done")

        result = await kernel.exec(
            handle,
            "import weebot_tools\nprint(weebot_tools.web_search('q'))",
            1.0,
            _server(slow).handle,
        )

        assert result.success, result.error
        assert result.stdout == "done\n"

    @pytest.mark.asyncio
    async def test_code_that_runs_too_long_still_times_out(self, kernel):
        handle = await kernel.start()
        result = await kernel.exec(handle, "while True: pass", 1.0, _server(_echo).handle)
        assert result.timed_out and result.died

    @pytest.mark.asyncio
    async def test_a_floor_blocks_a_command_called_from_code(self, kernel):
        class _Shell(BaseTool):
            name: str = "bash"
            description: str = "shell"
            parameters: dict = {"type": "object", "properties": {}}
            calls: list = []

            async def execute(self, **kwargs) -> ToolResult:
                self.calls.append(kwargs)
                return ToolResult(output="ran")

        inner = _Shell()
        inner.calls = []
        guarded = GuardedTool.wrap(inner, default_guard_chain(include_egress=False), "enforce")

        async def through_the_guards(name, arguments):
            with approval_scope(approval=AutoApproval(), session_id="rpc-floor"):
                return await guarded.execute(**arguments)

        handle = await kernel.start()
        code = (
            "import weebot_tools\n"
            "for cmd in ('rm -rf /', 'rm -rf ~'):\n"
            "    try:\n        weebot_tools.bash(cmd)\n"
            "    except weebot_tools.ToolError as e:\n        print('blocked:', e)\n"
        )
        result = await kernel.exec(handle, code, 20, _server(through_the_guards).handle)

        assert result.success, result.error
        assert result.stdout.count("blocked:") == 2
        assert inner.calls == []


class _Tools(FakeToolCollection):
    """Stands in for the registry; its python_execute makes a tool call the way the kernel does."""

    def __init__(self) -> None:
        super().__init__()
        self.reply: dict = {}
        self.dispatch_seen = None

    async def execute(self, _name: str, **kwargs):
        if _name == "python_execute":
            self.dispatch_seen = current_dispatch()
            self.reply = await _server(self.dispatch_seen).handle(_call("web_search", query="x"))
            return ToolResult(output="done")
        return await super().execute(_name, **kwargs)


@pytest.mark.asyncio
async def test_a_tool_call_from_code_goes_through_the_executor_and_taints_the_session():
    session = "sess-rpc-taint"
    get_session_scope().close(session)
    tools = _Tools()
    executor = ToolExecutor(tools=tools, egress_guard=make_guard())
    executor.set_step_context("step-1", session, "do it")
    try:
        await executor.execute_tool("python_execute", {"code": "x"})

        assert tools.dispatch_seen is not None
        assert tools.reply["result"]["output"] == "ok"
        assert [name for name, _ in tools.calls] == ["web_search"]
        assert get_session_scope().is_tainted(session)  # external output entered the session
        assert current_dispatch() is None  # the scope ended with the call
    finally:
        get_session_scope().close(session)
