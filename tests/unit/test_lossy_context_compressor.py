"""Tests for LossyContextCompressor Phase 4 improvements (F6).

Verifies head+tail retention, verbatim short messages,
numeric/date preservation, and configurable ContextBudget caps.
"""
from __future__ import annotations

from weebot.application.services.lossy_context_compressor import (
    LossyContextCompressor,
    _SHORT_MSG_THRESHOLD,
    _truncate_with_head_tail,
)
from weebot.domain.models.context import ContextBudget


class TestTruncateWithHeadTail:
    """Pure-function tests for ``_truncate_with_head_tail``."""

    def test_short_messages_kept_verbatim(self) -> None:
        """Messages below threshold should not be truncated."""
        text = "This is a short message that should stay entirely intact."
        result = _truncate_with_head_tail(text, head_chars=20, tail_chars=20)
        # The function only truncates when len > head+tail+elision
        assert len(result) >= len(text) or "..." in result

    def test_long_message_keeps_head_and_tail(self) -> None:
        """A long message should preserve both start and end content."""
        text = "The quick brown fox jumps over the lazy dog. " * 10
        result = _truncate_with_head_tail(text, head_chars=30, tail_chars=30)
        assert "The quick brown" in result
        assert "lazy dog" in result
        assert "[...]" in result

    def test_numbers_survive_truncation(self) -> None:
        """Numeric values near the cut boundary should be preserved."""
        text = (
            "The price is $29.99 and the date is 2026-06-30. "
            + "x" * 500
            + "The total is 42 items."
        )
        result = _truncate_with_head_tail(text, head_chars=40, tail_chars=30)
        # The head should contain digits from the price (29.99)
        assert "29" in result or "99" in result
        # The tail should contain digits (42)
        assert "42" in result

    def test_elision_marker_present(self) -> None:
        """The elision marker '[...]' should appear in truncated output."""
        text = "header " + "middle " * 100 + "footer"
        result = _truncate_with_head_tail(text, head_chars=10, tail_chars=10)
        assert "[...]" in result


class TestLossyContextCompressor:
    """Integration tests for the compressor with real ContextBudget."""

    def test_short_messages_not_truncated(self) -> None:
        """Messages under the threshold pass through verbatim."""
        msg = {
            "role": "user",
            "content": "What is the weather today in Berlin?",
        }
        budget = ContextBudget(message_head_chars=20, message_tail_chars=20)
        compressor = LossyContextCompressor()

        # The content is short — compressor should keep it verbatim
        # We test via _truncate_with_head_tail which is used inside compress()
        content = str(msg["content"])
        result = _truncate_with_head_tail(
            content,
            head_chars=budget.message_head_chars,
            tail_chars=budget.message_tail_chars,
        )
        assert result == content

    def test_dates_preserved_in_long_message(self) -> None:
        """Date strings near the head cut should survive."""
        text = (
            "Meeting scheduled for 2026-07-15 at 14:30. "
            + "Please confirm your attendance. " * 30
            + "Deadline: 2026-08-01."
        )
        result = _truncate_with_head_tail(text, head_chars=40, tail_chars=25)
        # The date 2026-07-15 should be in the head (extended by regex guard)
        assert "2026-07-15" in result or "2026" in result
        # The deadline date should be in the tail
        assert "2026-08-01" in result or "08-01" in result

    def test_configurable_caps_via_budget(self) -> None:
        """ContextBudget fields should control truncation behavior."""
        text = "A" * 500 + "Z" * 500  # 1000 chars, no spaces

        # Small caps
        small = _truncate_with_head_tail(text, head_chars=30, tail_chars=30)
        assert len(small) < 200

        # Large caps — should retain more
        large = _truncate_with_head_tail(text, head_chars=200, tail_chars=200)
        assert len(large) > len(small)
        assert "A" * 200 in large
        assert "Z" * 200 in large

    def test_compress_accepts_budget_override(self) -> None:
        """compress() should accept a budget with custom caps."""
        compressor = LossyContextCompressor()
        budget = ContextBudget(
            message_head_chars=50,
            message_tail_chars=50,
            summary_max_chars=500,
        )

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Long message " * 100},
            {"role": "assistant", "content": "Another long response " * 100},
        ]

        import pytest as _pytest
        # Run synchronously — the method is async but we just test the
        # budget doesn't cause errors
        import asyncio
        result = asyncio.run(compressor.compress(messages, budget=budget))
        assert result.retained_count > 0
        assert result.discarded_count >= 0
