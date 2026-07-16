"""Unit tests for PonytailPostProcessor."""
from __future__ import annotations

import pytest

from weebot.application.services.ponytail_post_processor import PonytailPostProcessor


@pytest.fixture
def processor() -> PonytailPostProcessor:
    return PonytailPostProcessor()


class TestPonytailPostProcessor:
    """Prose truncation after code fences."""

    def test_empty_text_unchanged(self, processor):
        assert processor.truncate("") == ""

    def test_text_without_code_fence_unchanged(self, processor):
        text = "Just some prose.\nMore prose."
        assert processor.truncate(text) == text

    def test_short_trailing_prose_unchanged(self, processor):
        text = "```python\nprint('hi')\n```\nShort note."
        assert processor.truncate(text) == text

    def test_long_trailing_prose_truncated(self, processor):
        text = (
            "```python\nprint('hi')\n```\n"
            "Line one of justification.\n"
            "Line two of justification.\n"
            "Line three of justification.\n"
            "Line four should be removed.\n"
            "Line five should also be removed."
        )
        result = processor.truncate(text)
        assert "Line three of justification." in result
        assert "Line four should be removed." not in result
        assert "Line five should also be removed." not in result
        assert "```python" in result

    def test_multiple_code_blocks_keep_last_block(self, processor):
        text = (
            "```python\nprint(1)\n```\n"
            "First prose.\n\n"
            "```python\nprint(2)\n```\n"
            "One.\nTwo.\nThree.\nFour."
        )
        result = processor.truncate(text)
        assert "print(2)" in result
        assert "One." in result
        assert "Two." in result
        assert "Three." in result
        assert "Four." not in result
        assert "First prose." in result
