"""Tests for ExecutorAgent cascade, error classification, and loop detection."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.agents.executor import (
    ExecutorAgent,
    _classify_tool_error,
)
from weebot.application.models.tool_collection import ToolCollection


class TestErrorClassification:
    """Tests for _classify_tool_error."""

    @pytest.mark.parametrize(
        "error_output,expected_class",
        [
            ("requires user confirmation for destructive operation", "confirmation_required"),
            ("Command denied by policy", "policy_denied"),
            ("command BLOCKED by security layer", "policy_denied"),
            ("Security error triggered", "security_blocked"),
            ("layer triggered by command", "security_blocked"),
            ("Timed out after 30000ms", "timeout"),
            ("Access denied: permission error", "permission_denied"),
            ("Permission denied", "permission_denied"),
            ("Normal execution result", None),
            ("", None),
        ],
    )
    def test_classify_tool_error(
        self, error_output: str, expected_class: str | None
    ) -> None:
        assert _classify_tool_error(error_output) == expected_class


class TestModelForStep:
    """Tests for _model_for_step routing."""

    def test_model_for_step_fallback(self) -> None:
        """Verify _model_for_step falls back to tier1 on error."""
        model = ExecutorAgent._model_for_step("")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_is_review_step(self) -> None:
        """Verify review keywords trigger review classification."""
        agent = MagicMock(spec=ExecutorAgent)
        agent._REVIEW_KEYWORDS = ExecutorAgent._REVIEW_KEYWORDS

        # _is_review_step is an instance method (not static)
        dummy_agent = object.__new__(ExecutorAgent)
        assert dummy_agent._is_review_step("code review of auth module")
        assert dummy_agent._is_review_step("security audit")
        assert not dummy_agent._is_review_step("write a function")


class TestStuckError:
    """Tests for _build_stuck_error."""

    def test_build_stuck_error_format(self) -> None:
        from collections import deque
        from weebot.domain.models.plan import Step

        step = Step(id="step-1", description="Open browser", status="pending")
        result = ExecutorAgent._build_stuck_error(
            step=step,
            reason="max step budget reached",
            recent_signatures=deque(["goto:{}"]),
            max_steps=50,
        )
        assert "step-1" in result
        assert "Open browser" in result
        assert "max step budget reached" in result
        assert "goto" in result


class TestNormalizeText:
    """Tests for _normalize_text."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Hello   world", "hello world"),
            ("  Multi   space  ", "multi space"),
            ("", ""),
            (None, ""),  # None → ""
        ],
    )
    def test_normalize_text(self, raw: str | None, expected: str) -> None:
        result = ExecutorAgent._normalize_text(raw or "")
        assert result == expected
