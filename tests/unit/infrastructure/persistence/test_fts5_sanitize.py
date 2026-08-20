"""Tests for L17 FTS5 query sanitization."""

from weebot.infrastructure.persistence.fts5_search import _sanitize_fts_query


class TestFts5Sanitize:
    """L17 — FTS5 query tokens are quoted and operators neutralised."""

    def test_simple_token_quoted(self):
        assert _sanitize_fts_query("hello") == '"hello"'

    def test_multi_word_and_joined(self):
        assert _sanitize_fts_query("hello world") == '"hello" AND "world"'

    def test_neutralizes_near(self):
        assert _sanitize_fts_query("foo NEAR bar") == '"foo" AND "NEAR" AND "bar"'

    def test_escapes_embedded_quotes(self):
        assert _sanitize_fts_query('say "hello"') == '"say" AND """hello"""'

    def test_empty_string(self):
        assert _sanitize_fts_query("") == ""

    def test_strips_leading_trailing_whitespace(self):
        assert _sanitize_fts_query("  hello  ") == '"hello"'
