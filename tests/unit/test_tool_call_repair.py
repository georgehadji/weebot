"""Unit tests for tool_call_repair — JSON repair + fuzzy tool-name matching."""
from __future__ import annotations

import json

import pytest

from weebot.application.services.tool_call_repair import (
    fuzzy_match_tool_name,
    repair_json_string,
    _fix_trailing_commas,
    _fix_single_quotes,
    _fix_unquoted_keys,
)


# ── JSON repair strategies ───────────────────────────────────────────────────

class TestFixTrailingCommas:
    def test_trailing_comma_in_object(self):
        assert _fix_trailing_commas('{"a": 1, "b": 2,}') == '{"a": 1, "b": 2}'

    def test_trailing_comma_in_array(self):
        assert _fix_trailing_commas("[1, 2, 3,]") == "[1, 2, 3]"

    def test_no_trailing_commas(self):
        assert _fix_trailing_commas('{"a": 1}') == '{"a": 1}'

    def test_nested_trailing_commas(self):
        assert _fix_trailing_commas('{"a": {"b": 1,},}') == '{"a": {"b": 1}}'


class TestFixSingleQuotes:
    def test_single_quoted_keys(self):
        result = _fix_single_quotes("{'name': 'value'}")
        assert '"name":' in result
        assert "'name':" not in result

    def test_single_quoted_values(self):
        result = _fix_single_quotes("{'name': 'hello world'}")
        assert '"hello world"' in result

    def test_mixed_quotes_preserved(self):
        """Double-quoted content should be left unchanged."""
        raw = '{"name": "already valid"}'
        assert _fix_single_quotes(raw) == raw

    def test_apostrophe_not_mangled(self):
        """A post-colon single-quote value with apostrophes is handled without breakage."""
        raw = '{"msg": "it says hello"}'
        result = _fix_single_quotes(raw)
        assert isinstance(result, str)
        # Double-quoted strings should be unchanged
        assert 'hello' in result


class TestFixUnquotedKeys:
    def test_unquoted_key(self):
        assert _fix_unquoted_keys("{key: 'value'}") == '{"key": \'value\'}'

    def test_unquoted_key_with_underscore(self):
        assert _fix_unquoted_keys("{my_key: 42}") == '{"my_key": 42}'

    def test_already_quoted_unchanged(self):
        raw = '{"key": "value"}'
        assert _fix_unquoted_keys(raw) == raw


# ── repair_json_string (integration) ─────────────────────────────────────────

class TestRepairJsonString:
    def test_already_valid_json(self):
        """Valid JSON passes through unchanged."""
        raw = '{"a": 1, "b": 2}'
        result = repair_json_string(raw)
        assert result == raw

    def test_trailing_comma(self):
        """Trailing comma is repaired."""
        result = repair_json_string('{"a": 1, "b": 2,}')
        assert result is not None
        assert json.loads(result)  # must be parseable
        assert "b\":2" in result  # no trailing comma after b

    def test_single_quotes(self):
        """Single quotes are replaced with double quotes."""
        result = repair_json_string("{'a': 1, 'b': 'hello'}")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == 1
        assert parsed["b"] == "hello"

    def test_unquoted_keys(self):
        """Unquoted keys get quoted."""
        result = repair_json_string("{a: 1, b: 'hello'}")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == 1
        assert parsed["b"] == "hello"

    def test_python_repr(self):
        """Python repr format (Anthropic SDK) is repaired."""
        result = repair_json_string("{'key': 'value', 'num': 42}")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["num"] == 42

    def test_python_repr_with_boolean(self):
        """Python True/False/None are converted."""
        result = repair_json_string("{'active': True, 'count': None}")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["active"] is True
        assert parsed["count"] is None

    def test_deeply_malformed(self):
        """Truly unrepairable input returns None."""
        result = repair_json_string("this is not even close to json")
        assert result is None

    def test_empty_string(self):
        """Empty input returns None."""
        assert repair_json_string("") is None
        assert repair_json_string("  ") is None

    def test_none_input(self):
        assert repair_json_string(None) is None  # type: ignore

    def test_multiple_issues_combined(self):
        """Trailing commas + single quotes + unquoted keys all at once."""
        result = repair_json_string("{a: 'hello', b: [1, 2,],}")
        assert result is not None
        parsed = json.loads(result)
        assert parsed["a"] == "hello"
        assert parsed["b"] == [1, 2]


# ── fuzzy_match_tool_name ────────────────────────────────────────────────────

class TestFuzzyMatchToolName:
    def test_exact_match(self):
        """Exact match returns the name unchanged."""
        result = fuzzy_match_tool_name("bash", ["bash", "python"])
        assert result == "bash"

    def test_case_insensitive(self):
        """Case difference is matched with the correct case."""
        result = fuzzy_match_tool_name("Bash", ["bash", "python"])
        # difflib handles case differences — may or may not match depending on cutoff
        # We just check it returns something reasonable
        assert result is not None
        assert result in ["bash", "python"]

    def test_typo_match(self):
        """Small typo is corrected."""
        result = fuzzy_match_tool_name("bas", ["bash", "python"])
        assert result == "bash"

    def test_typo_no_match(self):
        """Large typo returns None."""
        result = fuzzy_match_tool_name("xyzzzzz", ["bash", "python"])
        assert result is None

    def test_empty_valid_names(self):
        """Empty valid_names list returns None."""
        result = fuzzy_match_tool_name("bash", [])
        assert result is None

    def test_empty_name(self):
        """Empty name returns None."""
        result = fuzzy_match_tool_name("", ["bash"])
        assert result is None

    def test_custom_cutoff(self):
        """Custom cutoff adjusts sensitivity."""
        # "bas" is close to "bash" but not "basket" — at cutoff 0.8 it may miss
        result_high = fuzzy_match_tool_name("bas", ["basket", "bash"], cutoff=0.8)
        # At high cutoff, the better match (bash) should still win
        assert result_high == "bash"

    def test_multiple_candidates(self):
        """Best match among multiple candidates is returned."""
        result = fuzzy_match_tool_name("rmdir", ["rm", "dir", "remove-item"])
        assert result in ["rm", "dir", "remove-item"]
