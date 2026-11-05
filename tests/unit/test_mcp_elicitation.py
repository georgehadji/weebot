"""H12: an MCP server asks the person a question mid-call."""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest
from mcp.types import ElicitRequestFormParams, ElicitRequestURLParams, ElicitResult

from weebot.application.ports.mcp_elicitation_port import ElicitationReply
from weebot.application.ports.mcp_sampling_port import CallContext
from weebot.application.services.elicitation_broker import ElicitationBroker, form_problem
from weebot.application.services.tool_approval import (
    AutoApproval,
    ConsoleApproval,
    DenyApproval,
    FlowPauseApproval,
)
from weebot.domain.models.mcp import MCPServerConfig
from weebot.infrastructure.mcp import mcp_client_manager as mod
from weebot.infrastructure.mcp.session_callbacks import make_elicitation_callback

FORM = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "title": "Your name"},
        "age": {"type": "integer"},
        "ok": {"type": "boolean"},
        "tier": {"type": "string", "enum": ["a", "b"]},
    },
    "required": ["name"],
}


def _asker(*answers):
    queue = list(answers)
    prompts = []

    async def ask(prompt):
        prompts.append(prompt)
        return queue.pop(0)

    ask.prompts = prompts
    return ask


def _broker(*answers, approval=None):
    ask = _asker(*answers)
    return ElicitationBroker(ask, approval=lambda: approval or ConsoleApproval(ask)), ask


@pytest.mark.asyncio
async def test_a_person_at_the_terminal_fills_the_form():
    broker, ask = _broker("y", "Ada", "36", "yes", "b")

    reply = await broker.elicit("srv", "who are you?", FORM, session_id="s1")

    assert reply == ElicitationReply(
        "accept", {"name": "Ada", "age": 36, "ok": True, "tier": "b"}
    )
    assert "srv" in ask.prompts[0] and "who are you?" in ask.prompts[0]


@pytest.mark.asyncio
async def test_an_optional_field_can_be_skipped_and_a_bad_value_is_asked_again():
    broker, ask = _broker("y", "Ada", "old", "36", "", "")

    reply = await broker.elicit("srv", "m", FORM, session_id="s1")

    assert reply.content == {"name": "Ada", "age": 36}
    assert "whole number" in ask.prompts[3]  # the second ask for age says why


@pytest.mark.asyncio
async def test_no_and_cancel_are_passed_on():
    assert (await _broker("n")[0].elicit("s", "m", FORM, session_id="x")).action == "decline"
    assert (await _broker("c")[0].elicit("s", "m", FORM, session_id="x")).action == "cancel"
    assert (await _broker("y", "")[0].elicit("s", "m", FORM, session_id="x")).action == "cancel"


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [AutoApproval(), DenyApproval(), FlowPauseApproval()])
async def test_a_channel_with_no_terminal_declines_without_asking(channel):
    broker, ask = _broker("y", approval=channel)

    reply = await broker.elicit("srv", "m", FORM, session_id="s1")

    assert reply.action == "decline" and ask.prompts == []


@pytest.mark.asyncio
async def test_a_request_outside_a_tool_call_declines():
    broker, ask = _broker("y")
    assert (await broker.elicit("srv", "m", FORM, session_id="")).action == "decline"
    assert ask.prompts == []


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "object", "properties": {}},
        {"type": "object", "properties": {"a": {"type": "object"}}},
        {"type": "object", "properties": {"api_key": {"type": "string"}}},
        {"type": "object", "properties": {"x": {"type": "string", "format": "password"}}},
        {"type": "object", "properties": {f"f{i}": {"type": "string"} for i in range(11)}},
    ],
)
def test_a_form_the_broker_cannot_show_whole_or_that_asks_for_a_secret_is_refused(schema):
    assert form_problem(schema)


def test_a_flat_form_is_accepted():
    assert form_problem(FORM) is None


@pytest.mark.asyncio
async def test_eof_at_the_prompt_cancels():
    async def ask(prompt):
        raise EOFError

    broker = ElicitationBroker(ask, approval=lambda: ConsoleApproval(ask))
    assert (await broker.elicit("s", "m", FORM, session_id="x")).action == "cancel"


class _Broker:
    def __init__(self):
        self.seen = []

    async def elicit(self, server, message, schema, *, session_id=""):
        self.seen.append((server, message, session_id))
        return ElicitationReply("accept", {"a": "b"})


@pytest.mark.asyncio
async def test_the_callback_uses_the_call_in_flight_and_returns_the_reply():
    broker = _Broker()
    callback = make_elicitation_callback("srv", broker, lambda: CallContext("s1", False))
    params = ElicitRequestFormParams(message="hi", requestedSchema=FORM)

    result = await callback(None, params)

    assert isinstance(result, ElicitResult) and result.action == "accept"
    assert result.content == {"a": "b"}
    assert broker.seen == [("srv", "hi", "s1")]


@pytest.mark.asyncio
async def test_a_url_request_is_declined_without_asking():
    broker = _Broker()
    callback = make_elicitation_callback("srv", broker, lambda: CallContext("s1", False))
    params = ElicitRequestURLParams(message="go", url="https://x", elicitationId="1")

    assert (await callback(None, params)).action == "decline"
    assert broker.seen == []


@pytest.mark.asyncio
async def test_a_server_gets_the_elicitation_callback_only_when_its_config_enables_it(monkeypatch):
    captured = []

    class FakeSession:
        def __init__(self, r, w, sampling_callback=None, elicitation_callback=None):
            captured.append(elicitation_callback)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            pass

        async def list_tools(self):
            return None

    monkeypatch.setattr(mod, "ClientSession", FakeSession)
    manager = mod.MCPClientManager({}, elicitation_broker=_Broker())
    for enabled in (True, False):
        config = MCPServerConfig(name="s", command="x", elicitation_enabled=enabled)
        async with AsyncExitStack() as stack:
            await manager._open_session(config, (None, None), stack)

    assert callable(captured[0]) and captured[1] is None


def test_no_broker_is_built_while_no_server_enables_elicitation():
    from weebot.application.di import Container

    build = Container._create_mcp_elicitation_broker
    assert build({"a": {"command": "x"}, "b": {"elicitation_enabled": False}}) is None
    assert build({"a": {"elicitation_enabled": True}}) is not None
