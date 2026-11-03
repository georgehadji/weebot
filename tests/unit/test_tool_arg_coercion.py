"""Tool arguments are fitted to the tool's schema, and middleware can rewrite or deny a call (H16)."""

from __future__ import annotations

import pytest

from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.middleware.base import Deny, Middleware, ToolCall
from weebot.application.middleware.chain import MiddlewareChain
from weebot.application.models.tool_collection import ToolCollection
from weebot.application.services.tool_arg_coercion import coerce_args
from weebot.tools.base import BaseTool, ToolResult

SCHEMA = {
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "ratio": {"type": "number"},
        "flag": {"type": "boolean"},
        "tags": {"type": "array"},
        "opts": {"type": "object", "properties": {"depth": {"type": "integer"}}},
        "mode": {"type": "string", "enum": ["fast", "slow"]},
        "note": {"type": "string"},
    },
    "required": ["count"],
}


def test_scalars_are_cast_when_the_schema_says_so():
    out, log = coerce_args(SCHEMA, {"count": "3", "ratio": "4.2", "flag": "TRUE"})
    assert out == {"count": 3, "ratio": 4.2, "flag": True}
    assert [c.rule for c in log] == ["str_to_int", "str_to_number", "str_to_bool"]


def test_a_string_stays_a_string_when_the_schema_says_string():
    assert coerce_args(SCHEMA, {"count": 1, "note": "42"})[0]["note"] == "42"


def test_json_strings_and_scalars_become_arrays_and_objects():
    out, _ = coerce_args(SCHEMA, {"count": 1, "tags": "[1, 2]", "opts": '{"depth": "2"}'})
    assert out["tags"] == [1, 2]
    assert out["opts"] == {"depth": 2}
    assert coerce_args(SCHEMA, {"count": 1, "tags": "solo"})[0]["tags"] == ["solo"]


def test_array_items_are_coerced_with_the_items_schema():
    schema = {
        "type": "object",
        "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
    }
    assert coerce_args(schema, {"ids": '[1, "2"]'})[0]["ids"] == [1, 2]


def test_a_null_optional_is_dropped_but_a_required_field_is_never_invented():
    out, log = coerce_args(SCHEMA, {"note": None})
    assert out == {} and [c.rule for c in log] == ["drop_null"]
    assert "count" not in coerce_args(SCHEMA, {"note": "x"})[0]
    assert coerce_args(SCHEMA, {"count": None})[0] == {"count": None}  # required: left alone


def test_enum_values_match_case_insensitively():
    assert coerce_args(SCHEMA, {"count": 1, "mode": "FAST"})[0]["mode"] == "fast"
    assert coerce_args(SCHEMA, {"count": 1, "mode": "medium"})[0]["mode"] == "medium"


@pytest.mark.parametrize("bad", ["abc", "1.5", "", "nan"])
def test_values_that_do_not_parse_pass_through_for_the_tool_to_reject(bad):
    assert coerce_args(SCHEMA, {"count": bad})[0]["count"] == bad


def test_unknown_keys_and_missing_schemas_pass_through():
    assert coerce_args(SCHEMA, {"count": 1, "extra": "9"})[0]["extra"] == "9"
    assert coerce_args(None, {"a": "1"})[0] == {"a": "1"}


class _Echo(BaseTool):
    name: str = "echo"
    description: str = "echoes its arguments"
    parameters: dict = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    seen: list = []

    async def execute(self, **kwargs) -> ToolResult:
        self.seen.append(kwargs)
        return ToolResult(output="x" * 10)


class _Deny(Middleware):
    def name(self):
        return "deny"

    async def before_tool_call(self, call):
        return Deny("policy says no")


class _Shout(Middleware):
    def name(self):
        return "shout"

    async def before_tool_call(self, call):
        return ToolCall(call.name, {**call.arguments, "count": call.arguments["count"] + 1})

    async def transform_tool_result(self, call, result):
        result.output = result.output.upper() + f"|{call.name}"
        return result


def _echo():
    tool = _Echo()
    tool.seen = []
    return tool


@pytest.mark.asyncio
async def test_the_executor_coerces_before_dispatch_and_reports_it():
    tool = _echo()
    result = await ToolExecutor(tools=ToolCollection(tool)).execute_tool("echo", '{"count": "3"}')
    assert tool.seen == [{"count": 3}]
    assert result.metadata["coerced"][0]["rule"] == "str_to_int"


@pytest.mark.asyncio
async def test_a_denying_middleware_stops_the_call_with_a_structured_error():
    tool = _echo()
    chain = MiddlewareChain([_Deny(), _Shout()])
    executor = ToolExecutor(tools=ToolCollection(tool), middleware_chain=chain)
    result = await executor.execute_tool("echo", {"count": 1})
    assert result.is_error and "policy says no" in result.error and "echo" in result.error
    assert tool.seen == []


@pytest.mark.asyncio
async def test_middleware_can_rewrite_the_call_and_the_result():
    tool = _echo()
    executor = ToolExecutor(tools=ToolCollection(tool), middleware_chain=MiddlewareChain([_Shout()]))
    result = await executor.execute_tool("echo", {"count": 1})
    assert tool.seen == [{"count": 2}]
    assert result.output == "XXXXXXXXXX|echo"


@pytest.mark.asyncio
async def test_without_a_chain_nothing_changes():
    tool = _echo()
    result = await ToolExecutor(tools=ToolCollection(tool)).execute_tool("echo", {"count": 5})
    assert tool.seen == [{"count": 5}] and result.output == "x" * 10
