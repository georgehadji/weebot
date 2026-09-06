"""D48 — a tool registered via `dynamic_tools` must actually be callable.

The claim on record was that `_wrap_base_tool` "forwards unvalidated
**kwargs to tool.execute()". Measurement refuted it: nothing was forwarded,
because nothing ever reached `execute`. The MCP SDK builds a tool's
advertised JSON Schema by introspecting the registered function, and it does
not understand `**kwargs` -- it read the bare `**kwargs` as one *required
string* parameter literally named "kwargs". Every call therefore failed
argument validation first:

    CALL {'a': 1, 'b': 'x'}     -> ToolError: 1 validation error ... kwargs Field required
    CALL {}                     -> ToolError: 1 validation error ... kwargs Field required
    CALL {'path': '../../etc'}  -> ToolError: 1 validation error ... kwargs Field required

So the defect was not a missing check. It was that `list_tools` advertised a
tool that no client could invoke, under any arguments at all -- including
none. These tests pin the schema the SDK derives *and* the arguments
`execute` actually receives, because the first was the thing that silently
went wrong.
"""

from __future__ import annotations

import json

import pytest

from weebot.domain.models.base_tool import BaseTool
from weebot.mcp.server import WeebotMCPServer


class _Result:
    def __init__(self, output: str, is_error: bool = False, error: str | None = None) -> None:
        self.output = output
        self.is_error = is_error
        self.error = error


class EchoTool(BaseTool):
    """Records exactly the kwargs `execute` was handed."""

    name: str = "echo_tool"
    description: str = "Echo the arguments back as JSON."
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "path": {"type": "string"},
            "count": {"type": "integer"},
            "flag": {"type": "boolean"},
        },
        "required": ["command"],
    }

    async def execute(self, **kwargs):
        return _Result(json.dumps(kwargs, sort_keys=True))


class NoParamTool(BaseTool):
    name: str = "noparams"
    description: str = "Takes nothing."
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return _Result(json.dumps(kwargs, sort_keys=True))


class OddNameTool(BaseTool):
    """Declares parameter names that cannot appear in a Python signature."""

    name: str = "odd_names"
    description: str = "Has a hyphenated name and a reserved word."
    parameters: dict = {
        "type": "object",
        "properties": {
            "good": {"type": "string"},
            "bad-name": {"type": "string"},
            "class": {"type": "string"},
        },
        "required": ["good"],
    }

    async def execute(self, **kwargs):
        return _Result(json.dumps(kwargs, sort_keys=True))


class MalformedSchemaTool(BaseTool):
    """`parameters` is a dict, but its contents are the wrong types."""

    name: str = "malformed"
    description: str = "Schema is garbage."
    parameters: dict = {"type": "object", "properties": "not-a-dict", "required": "nope"}

    async def execute(self, **kwargs):
        return _Result(json.dumps(kwargs, sort_keys=True))


class FailingTool(BaseTool):
    name: str = "failing"
    description: str = "Always reports an error."
    parameters: dict = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

    async def execute(self, **kwargs):
        return _Result("", is_error=True, error="boom")


def _server() -> WeebotMCPServer:
    return WeebotMCPServer(
        dynamic_tools=[
            EchoTool(),
            NoParamTool(),
            OddNameTool(),
            MalformedSchemaTool(),
            FailingTool(),
        ]
    )


async def _schemas() -> dict[str, dict]:
    listed = await _server()._mcp.list_tools()
    return {t.name: t.inputSchema for t in listed}


async def _call(name: str, args: dict) -> str:
    """Invoke through the real MCP dispatch path and return the text content."""
    result = await _server()._mcp.call_tool(name, args)
    return "".join(getattr(c, "text", "") for c in result.content)


# --------------------------------------------------------------------------
# The schema the SDK derives — the thing that was silently wrong.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_advertised_schema_is_the_tools_own_schema():
    schema = (await _schemas())["echo_tool"]
    assert sorted(schema["properties"]) == ["command", "count", "flag", "path"]
    assert schema["required"] == ["command"]


@pytest.mark.asyncio
async def test_no_tool_advertises_a_parameter_named_kwargs():
    """The exact signature of the defect: `**kwargs` read as a field."""
    for name, schema in (await _schemas()).items():
        assert "kwargs" not in (schema.get("properties") or {}), (
            f"{name} still advertises the raw **kwargs placeholder"
        )


@pytest.mark.asyncio
async def test_declared_types_survive_into_the_schema():
    props = (await _schemas())["echo_tool"]["properties"]
    assert props["command"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["flag"]["type"] == "boolean"


# --------------------------------------------------------------------------
# What `execute` actually receives.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_supplied_argument_reaches_execute():
    got = json.loads(await _call("echo_tool", {"command": "run", "path": "/x", "count": 3, "flag": True}))
    assert got == {"command": "run", "path": "/x", "count": 3, "flag": True}


@pytest.mark.asyncio
async def test_an_omitted_optional_arrives_absent_not_as_none():
    """`execute(**kwargs)` must not be able to tell "omitted" from "sent as null"
    by accident. The SDK materialises every declared parameter, so without the
    strip an omitted `path` would arrive as an explicit None -- and
    `"path" in kwargs` would be True for a caller who never mentioned it."""
    got = json.loads(await _call("echo_tool", {"command": "run"}))
    assert got == {"command": "run"}
    assert "path" not in got


@pytest.mark.asyncio
async def test_a_tool_with_no_parameters_is_callable_with_no_arguments():
    assert json.loads(await _call("noparams", {})) == {}


@pytest.mark.asyncio
async def test_a_tool_error_still_reaches_the_client_as_iserror():
    """Regression vector: the pre-existing error contract is unchanged."""
    result = await _server()._mcp.call_tool("failing", {"x": "1"})
    assert result.isError is True
    assert "boom" in "".join(getattr(c, "text", "") for c in result.content)


# --------------------------------------------------------------------------
# Validation now happens, and happens against the tool's own schema.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_required_argument_is_rejected_by_name():
    with pytest.raises(Exception) as exc:
        await _call("echo_tool", {"path": "/x"})
    assert "command" in str(exc.value)


@pytest.mark.asyncio
async def test_an_argument_of_the_wrong_type_is_rejected_by_name():
    with pytest.raises(Exception) as exc:
        await _call("echo_tool", {"command": "run", "count": "not-an-int"})
    assert "count" in str(exc.value)


@pytest.mark.asyncio
async def test_an_undeclared_argument_never_reaches_execute():
    got = json.loads(await _call("echo_tool", {"command": "run", "zzz": "surprise"}))
    assert "zzz" not in got


# --------------------------------------------------------------------------
# Boundary: schemas that cannot be expressed as a Python signature.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_parameter_that_is_not_an_identifier_is_dropped_not_fatal():
    """A hyphenated or reserved name cannot be a Python parameter. The tool
    must still register and still work for the names that *are* expressible."""
    schema = (await _schemas())["odd_names"]
    assert sorted(schema["properties"]) == ["good"]
    assert json.loads(await _call("odd_names", {"good": "g"})) == {"good": "g"}


@pytest.mark.asyncio
async def test_an_unrepresentable_parameter_is_reported(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="weebot.mcp.server"):
        WeebotMCPServer._apply_schema_signature(
            lambda: None, OddNameTool().parameters, "odd_names"
        )
    assert "bad-name" in caplog.text and "class" in caplog.text


@pytest.mark.asyncio
async def test_a_malformed_schema_degrades_instead_of_crashing():
    """`properties` as a string used to be a plausible way to take the whole
    server down at construction time. It must register as a no-arg tool."""
    assert (await _schemas())["malformed"]["properties"] == {}
    assert json.loads(await _call("malformed", {})) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [None, "a string", [], 42, {}, {"properties": None}])
async def test_a_schema_of_any_shape_produces_a_usable_signature(schema):
    """`_apply_schema_signature` is the only thing standing between a
    malformed `parameters` and an unimportable server."""
    import inspect

    def fn() -> None: ...

    optional = WeebotMCPServer._apply_schema_signature(fn, schema, "probe")
    assert optional == set()
    assert list(inspect.signature(fn).parameters) == []
