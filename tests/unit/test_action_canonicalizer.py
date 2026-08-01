"""Unit tests for ActionCanonicalizer (Tier 1.1 — Action Realization Layer)."""
from __future__ import annotations

from weebot.domain.models.base_tool import BaseTool
from weebot.domain.models.canonical import CanonicalizationVerdict
from weebot.domain.models.tool_result import ToolResult
from weebot.infrastructure.adapters.action_canonicalizer import ActionCanonicalizer


class _StubTool(BaseTool):
    async def execute(self, **kwargs):  # pragma: no cover - not exercised
        return ToolResult(output="ok")


def _make_tool(name: str, parameters: dict) -> _StubTool:
    return _StubTool(name=name, description="stub", parameters=parameters)


SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer", "default": 5},
        "verbose": {"type": "boolean"},
    },
    "required": ["query"],
}


def test_unknown_tool_passes_through_unchanged():
    canon = ActionCanonicalizer(tools=[])
    result = canon.canonicalize("nonexistent_tool", {"a": 1})
    assert result.verdict == CanonicalizationVerdict.PASS
    assert result.corrected_args == {"a": 1}
    assert result.changes == []


def test_fills_missing_default():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool])
    result = canon.canonicalize("search", {"query": "weebot"})
    assert result.verdict == CanonicalizationVerdict.FILL_DEFAULT
    assert result.corrected_args["max_results"] == 5
    assert any("max_results" in c for c in result.changes)


def test_coerces_stringified_integer():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool])
    result = canon.canonicalize("search", {"query": "x", "max_results": "10"})
    assert result.corrected_args["max_results"] == 10
    assert isinstance(result.corrected_args["max_results"], int)


def test_coerces_stringified_boolean():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool])
    result = canon.canonicalize("search", {"query": "x", "verbose": "true"})
    assert result.corrected_args["verbose"] is True


def test_does_not_reinterpret_actual_bool_as_int():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool])
    result = canon.canonicalize(
        "search", {"query": "x", "verbose": False, "max_results": 5}
    )
    assert result.corrected_args["verbose"] is False
    assert result.changes == []


def test_coercion_disabled_leaves_types_untouched():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool], coerce_types=False)
    result = canon.canonicalize("search", {"query": "x", "max_results": "10"})
    assert result.corrected_args["max_results"] == "10"


def test_non_strict_missing_required_passes_through():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool], strict_mode=False)
    result = canon.canonicalize("search", {})
    assert result.verdict != CanonicalizationVerdict.BLOCK
    assert "query" not in result.corrected_args


def test_strict_mode_blocks_missing_required():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool], strict_mode=True)
    result = canon.canonicalize("search", {})
    assert result.verdict == CanonicalizationVerdict.BLOCK
    assert "query" in result.block_reason


def test_strict_mode_passes_when_required_present():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool], strict_mode=True)
    result = canon.canonicalize("search", {"query": "weebot"})
    assert result.verdict == CanonicalizationVerdict.FILL_DEFAULT
    assert result.corrected_args["query"] == "weebot"


def test_unparseable_string_left_unchanged():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool])
    result = canon.canonicalize("search", {"query": "x", "max_results": "not-a-number"})
    assert result.corrected_args["max_results"] == "not-a-number"


def test_original_args_untouched():
    tool = _make_tool("search", SEARCH_SCHEMA)
    canon = ActionCanonicalizer(tools=[tool])
    original = {"query": "x", "max_results": "10"}
    result = canon.canonicalize("search", original)
    assert original == {"query": "x", "max_results": "10"}
    assert result.original_args == {"query": "x", "max_results": "10"}
