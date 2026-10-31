"""R2 finding (2026-10-30): ``ponytail [mode]`` in a chat did nothing.

``BaseGateway.handle_ponytail_command`` had no caller since it was added, so the message
went to the agent as a task. Every gateway now answers it after its sender check, without
starting a run; an unauthorized sender cannot change the mode.
"""

from __future__ import annotations

import pathlib
from contextlib import asynccontextmanager

import pytest

from cli.commands import ponytail as ponytail_cli
from weebot.interfaces import factories
from weebot.interfaces.gateways import telegram as telegram_mod
from weebot.interfaces.gateways.base import GatewayMessage

GATEWAYS = pathlib.Path(__file__).parents[3] / "weebot" / "interfaces" / "gateways"


@pytest.fixture
def mode(monkeypatch):
    state = {"mode": "full", "writes": []}
    monkeypatch.setattr(ponytail_cli, "read_ponytail_mode", lambda: state["mode"])
    monkeypatch.setattr(ponytail_cli, "write_ponytail_mode", state["writes"].append)

    @asynccontextmanager
    async def _no_run(*a, **k):
        raise AssertionError("a ponytail command must not start a run")
        yield

    monkeypatch.setattr(factories, "run_scope", _no_run)
    monkeypatch.setattr(telegram_mod, "run_scope", _no_run)
    return state


def _signal():
    from weebot.interfaces.gateways.signal import SignalAdapter

    return SignalAdapter(state_repo=None, llm=None), "_process_message", "signal", {}


def _whatsapp():
    from weebot.interfaces.gateways.whatsapp import WhatsAppAdapter

    adapter = WhatsAppAdapter(token="t", phone_number_id="1", state_repo=None, llm=None)
    return adapter, "process_message", "whatsapp", {}


def _email():
    from weebot.interfaces.gateways.email import EmailAdapter

    meta = {"sender_authenticated": True}
    return EmailAdapter(state_repo=None, llm=None), "_process_message", "email", meta


def _telegram():
    from weebot.interfaces.gateways.telegram import TelegramAdapter

    adapter = TelegramAdapter(token="t", state_repo=None, llm=None, flow_resolver=None)
    return adapter, "_process_message", "telegram", {}


ADAPTERS = [_signal, _whatsapp, _email, _telegram]


async def _send(make, text, authorized=True):
    adapter, method, platform, meta = make()
    adapter.is_authorized = lambda *a, **k: authorized
    msg = GatewayMessage(platform=platform, external_id="a@b.example", text=text, metadata=meta)
    return await getattr(adapter, method)(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize("make", ADAPTERS)
async def test_ponytail_reports_the_mode(make, mode):
    assert "full" in await _send(make, "ponytail")
    assert mode["writes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("make", ADAPTERS)
async def test_ponytail_mode_sets_it(make, mode):
    assert "lite" in await _send(make, "Ponytail lite")
    assert mode["writes"] == ["lite"]


@pytest.mark.asyncio
@pytest.mark.parametrize("make", ADAPTERS)
async def test_an_unauthorized_sender_cannot_set_it(make, mode):
    reply = await _send(make, "ponytail off", authorized=False)
    assert mode["writes"] == []
    assert "off" not in (reply or "").replace("authorized", "")


@pytest.mark.parametrize("name", ["discord", "slack"])
def test_the_webhook_gateways_answer_it_after_the_sender_check(name):
    src = (GATEWAYS / f"{name}.py").read_text(encoding="utf-8")
    assert "handle_ponytail_command" in src
    run = min(src.index(m) for m in ("async with run_scope(", ".spawn(") if m in src)
    assert src.index("is_authorized(") < src.index("handle_ponytail_command") < run
