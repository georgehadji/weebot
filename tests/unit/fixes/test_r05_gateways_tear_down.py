"""R05 (audit 2026-10-29): every one-shot run tears its tools down.

The six gateways and ``POST /api/webhook/run`` built a fresh tool collection per message
and never closed it, so each message left its browser (Chromium), MCP clients and HTTP
sessions behind. TaskRunner closed its tools in ``finally``; the one-shot callers now get
the same guarantee from ``run_scope``.
"""

from __future__ import annotations

import contextlib
import pathlib

import pytest

from weebot.domain.models.session import Session
from weebot.interfaces import factories
from weebot.interfaces.gateways.base import GatewayMessage


class _Tools:
    def __init__(self) -> None:
        self.closed = 0

    async def teardown(self) -> None:
        self.closed += 1


class _Flow:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    async def run(self, text):
        if self.fail:
            raise RuntimeError("flow broke")
        yield type("E", (), {"type": "message", "message": f"echo {text}"})()


@pytest.fixture
def built(monkeypatch):
    made: list[_Tools] = []

    async def _build_tools(role="admin", **_):
        made.append(_Tools())
        return made[-1]

    monkeypatch.setattr(factories, "build_tools", _build_tools)
    monkeypatch.setattr(factories, "create_flow", lambda **kw: _Flow(kw["session"].id == "fail"))
    return made


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_run_scope_closes_the_tools_once(built, fail):
    session = Session(id="fail" if fail else "ok")
    with pytest.raises(RuntimeError) if fail else contextlib.nullcontext():
        async with factories.run_scope(session, llm=None) as flow:
            [e async for e in flow.run("hi")]
    assert [t.closed for t in built] == [1]


@pytest.mark.asyncio
async def test_a_gateway_message_closes_its_tools(built, monkeypatch):
    from weebot.interfaces.gateways.signal import SignalAdapter

    adapter = SignalAdapter(state_repo=None, llm=None)
    monkeypatch.setattr(adapter, "is_authorized", lambda *a: True)

    async def _handle(message):
        return message.text

    monkeypatch.setattr(adapter, "handle", _handle)
    reply = await adapter._process_message(
        GatewayMessage(platform="signal", external_id="100", text="hello")
    )
    assert reply == "echo hello"
    assert [t.closed for t in built] == [1]


def test_no_interface_builds_tools_outside_an_owner():
    """Only run_scope (factories), the CLI runner and the TaskRunner hand-off own tools."""
    root = pathlib.Path(factories.__file__).parent
    owners = {"factories.py", "agent_runner.py", "sessions.py"}
    callers = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if p.name not in owners and "build_tools(" in p.read_text("utf-8")
    )
    assert callers == []
