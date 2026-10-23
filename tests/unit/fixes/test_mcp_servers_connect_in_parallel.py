"""MCP servers connect in parallel, and each closes in the task that opened it.

They connected one after another (~7.4 s for four at every `flow run`). anyio
contexts must exit in the task that entered them, so each server now lives in
its own holder task until cleanup.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager

_TASKS: dict[str, tuple] = {}


@asynccontextmanager
async def _conn(name):
    entered = asyncio.current_task()
    await asyncio.sleep(0.3)  # a server that takes 0.3 s to start
    try:
        yield
    finally:
        _TASKS[name] = (entered, asyncio.current_task())


async def test_parallel_connect_and_same_task_close(monkeypatch):
    async def _connect_server(self, name, cfg, stack):
        await stack.enter_async_context(_conn(name))
        self._clients[name] = object()
        self._tools_cache[name] = []

    monkeypatch.setattr(MCPClientManager, "_connect_server", _connect_server)
    m = MCPClientManager({"mcpServers": {n: {"command": "x"} for n in ("a", "b", "c", "d")}})
    t = time.monotonic()
    await m.initialize()
    assert time.monotonic() - t < 0.9, "four 0.3 s servers should not take 1.2 s"
    assert set(m._clients) == {"a", "b", "c", "d"}
    await m.cleanup()
    assert all(entered is exited for entered, exited in _TASKS.values())


async def test_a_failing_server_does_not_stop_the_others(monkeypatch):
    async def _connect_server(self, name, cfg, stack):
        if name == "bad":
            raise RuntimeError("no such command")
        self._clients[name] = object()
        self._tools_cache[name] = []

    monkeypatch.setattr(MCPClientManager, "_connect_server", _connect_server)
    m = MCPClientManager({"mcpServers": {"bad": {}, "good": {}}}, max_retries=1)
    await m.initialize()
    assert set(m._clients) == {"good"}
    await m.cleanup()
