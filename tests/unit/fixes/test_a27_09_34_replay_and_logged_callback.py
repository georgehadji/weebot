"""A27 (Discord replay) and A34 (BashGuard callback must log)."""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from nacl.signing import SigningKey

from weebot.core.bash_guard import BashGuard


@pytest.fixture
def discord(mocker):
    import weebot.interfaces.gateways.base as gw_base
    from weebot.interfaces.gateways.discord import DiscordAdapter

    mocker.patch.object(gw_base, "SafetyChecker")
    key = SigningKey.generate()
    adapter = DiscordAdapter(
        public_key=key.verify_key.encode().hex(),
        bot_token="fake-bot-token",
        application_id="123456789",
        state_repo=AsyncMock(),
        llm=MagicMock(),
    )
    return adapter, key


def _signed(key, body: bytes, timestamp: str) -> str:
    return key.sign(timestamp.encode() + body).signature.hex()


def test_a_fresh_signed_interaction_is_accepted(discord):
    adapter, key = discord
    ts = str(int(time.time()))
    assert adapter.verify_signature(b'{"type":1}', _signed(key, b'{"type":1}', ts), ts) is True


def test_a_correctly_signed_but_old_interaction_is_rejected(discord):
    adapter, key = discord
    ts = str(int(time.time()) - 3600)
    assert adapter.verify_signature(b'{"type":1}', _signed(key, b'{"type":1}', ts), ts) is False


def test_a_non_numeric_timestamp_is_rejected(discord):
    adapter, key = discord
    assert adapter.verify_signature(b"{}", _signed(key, b"{}", "yesterday"), "yesterday") is False


def test_a_failing_security_callback_is_logged_not_swallowed(caplog):
    def boom(_risk):
        raise RuntimeError("metrics down")

    guard = BashGuard(on_security_event=boom)
    with caplog.at_level(logging.WARNING):
        risk, _ = guard.evaluate("rm -rf /")
    assert risk.name in {"DANGEROUS", "BLOCKED"}
    assert any("metrics down" in r.getMessage() or r.exc_info for r in caplog.records)
