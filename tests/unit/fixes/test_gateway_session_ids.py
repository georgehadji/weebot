"""Real sender ids make valid Session ids (found during audit 2026-10-29, wave 4).

Gateways built the Session id as ``f"{platform}-{sender}-{suffix}"``. A Signal sender is a
phone number such as ``+306912345678`` and an email sender is an address, but Session ids
allow only letters, digits, dot, underscore and hyphen, so every real Signal or email
message raised ``ValueError`` before its run started.
"""

from __future__ import annotations

import pytest

from weebot.domain.models.session import Session
from weebot.interfaces import factories
from weebot.interfaces.gateways.base import GatewayMessage, flow_session_id


class _Tools:
    async def teardown(self) -> None:
        return None


class _Flow:
    async def run(self, text):
        yield type("E", (), {"type": "message", "message": f"echo {text}"})()


@pytest.fixture
def sessions(monkeypatch):
    seen: list[Session] = []

    async def _build_tools(role="admin", **_):
        return _Tools()

    def _create_flow(**kw):
        seen.append(kw["session"])
        return _Flow()

    monkeypatch.setattr(factories, "build_tools", _build_tools)
    monkeypatch.setattr(factories, "create_flow", _create_flow)
    return seen


async def _allow(adapter, monkeypatch):
    async def _handle(message):
        return message.text

    monkeypatch.setattr(adapter, "is_authorized", lambda *a: True)
    monkeypatch.setattr(adapter, "handle", _handle)


@pytest.mark.asyncio
async def test_a_signal_phone_number_runs(sessions, monkeypatch):
    from weebot.interfaces.gateways.signal import SignalAdapter

    adapter = SignalAdapter(state_repo=None, llm=None)
    await _allow(adapter, monkeypatch)
    reply = await adapter._process_message(
        GatewayMessage(platform="signal", external_id="+306912345678", text="hi")
    )
    assert reply == "echo hi"
    assert sessions[0].id.startswith("signal-_306912345678-")
    assert sessions[0].user_id == "signal-+306912345678"


@pytest.mark.asyncio
async def test_an_email_address_runs(sessions, monkeypatch):
    from weebot.interfaces.gateways.email import EmailAdapter

    adapter = EmailAdapter(state_repo=None, llm=None, imap_user="bot@corp.example")
    await _allow(adapter, monkeypatch)
    reply = await adapter._process_message(
        GatewayMessage(
            platform="email",
            external_id="Ann.Lee@Example.com",
            text="hi",
            metadata={"sender_authenticated": True},
        )
    )
    assert reply == "echo hi"
    assert sessions[0].id.startswith("email-ann.lee_example.com-")


def test_a_long_sender_still_fits():
    sid = flow_session_id("email", "x" * 300 + "@example.com")
    assert Session(id=sid).id == sid
