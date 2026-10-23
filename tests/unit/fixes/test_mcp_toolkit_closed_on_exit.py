"""The CLI closes its MCP connections before the event loop ends.

Found on the 2026-10-23 smoke run: every `flow run` with a configured MCP
server (postiz) ended in "Attempted to exit cancel scope in a different task
than it was entered in". The streamable-HTTP client opened by
`factories._configured_mcp_tools` was never closed, so asyncio finalised its
generator at shutdown from another task.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.interfaces import factories


class _Toolkit:
    closed = 0

    async def cleanup(self):
        _Toolkit.closed += 1


@pytest.mark.asyncio
async def test_close_mcp_toolkit_cleans_up_and_forgets(monkeypatch):
    _Toolkit.closed = 0
    monkeypatch.setattr(factories, "_MCP_TOOLKIT", _Toolkit())
    await factories.close_mcp_toolkit()
    assert _Toolkit.closed == 1 and factories._MCP_TOOLKIT is None
    await factories.close_mcp_toolkit()  # nothing open: a no-op
    assert _Toolkit.closed == 1


def test_the_cli_wrapper_closes_it(monkeypatch):
    from cli.commands import flow as flow_cmd

    _Toolkit.closed = 0
    monkeypatch.setattr(factories, "_MCP_TOOLKIT", _Toolkit())

    async def _work():
        await asyncio.sleep(0)

    flow_cmd._run_async(_work)
    assert _Toolkit.closed == 1
