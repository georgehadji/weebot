"""R09 (audit 2026-10-29): Discord gets its answer within three seconds.

Discord drops an interaction that is not answered within 3 s. The adapter ran the whole
plan-act flow before answering, so every real command timed out and the user saw "The
application did not respond". It now answers at once with a deferred response (type 5),
runs the flow in a background task and edits the original reply when the run ends.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.interfaces import factories
from weebot.interfaces.gateways import discord as discord_mod
from weebot.interfaces.gateways.discord import DiscordAdapter

_KEY = "c12a20a80a7d4600647e751ec5ca00d639c3907dc595f9d619b773c407f5a4fe"
_PAYLOAD = {
    "type": 2,
    "application_id": "app-1",
    "data": {"name": "ask", "options": [{"name": "question", "value": "hello"}]},
    "channel_id": "123456",
    "member": {"user": {"id": "42", "username": "u"}},
    "token": "tok-1",
    "id": "i-1",
}


class _Tools:
    async def teardown(self):
        return None


def _adapter(monkeypatch, reply: str | Exception) -> tuple[DiscordAdapter, list]:
    adapter = DiscordAdapter(
        public_key=_KEY, bot_token="t", application_id="", state_repo=None, llm=None
    )
    monkeypatch.setattr(adapter, "is_authorized", lambda *a: True)
    edits: list = []

    async def _edit(application_id, token, content):
        edits.append((application_id, token, content))
        return True

    monkeypatch.setattr(adapter, "_edit_original", _edit)

    class _Flow:
        async def run(self, text):
            if isinstance(reply, Exception):
                raise reply
            yield type("E", (), {"type": "message", "message": reply})()

    async def _build_tools(role="admin", **_):
        return _Tools()

    monkeypatch.setattr(factories, "build_tools", _build_tools)
    monkeypatch.setattr(factories, "create_flow", lambda **_: _Flow())
    return adapter, edits


async def _drain():
    await asyncio.gather(
        *[t for t in asyncio.all_tasks() if t.get_name().startswith("discord-")]
    )


@pytest.mark.asyncio
async def test_the_interaction_is_deferred_and_then_edited(monkeypatch):
    adapter, edits = _adapter(monkeypatch, "x" * 2500)
    assert await adapter.process_interaction(_PAYLOAD) == {"type": 5}
    assert edits == []  # nothing ran before the answer went back
    await _drain()
    assert edits == [("app-1", "tok-1", "x" * 2000)]


@pytest.mark.asyncio
async def test_a_failing_run_edits_in_an_error(monkeypatch):
    adapter, edits = _adapter(monkeypatch, RuntimeError("boom"))
    assert (await adapter.process_interaction(_PAYLOAD))["type"] == 5
    await _drain()
    assert len(edits) == 1 and "failed" in edits[0][2].lower()


@pytest.mark.asyncio
async def test_the_edit_patches_the_original_message(monkeypatch):
    calls: list = []

    class _Resp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def text(self):
            return ""

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def patch(self, url, json):
            calls.append((url, json))
            return _Resp()

    monkeypatch.setattr(discord_mod.aiohttp, "ClientSession", _Session)
    adapter = DiscordAdapter(
        public_key=_KEY, bot_token="t", application_id="", state_repo=None, llm=None
    )
    assert await adapter._edit_original("app-1", "tok-1", "hi")
    assert calls == [
        ("https://discord.com/api/v10/webhooks/app-1/tok-1/messages/@original", {"content": "hi"})
    ]
