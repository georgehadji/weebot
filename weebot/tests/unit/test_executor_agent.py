"""Tests for ExecutorAgent cascade, error classification, and loop detection."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from collections import deque

from weebot.application.agents.executor import (
    ExecutorAgent,
    _classify_tool_error,
)
from weebot.application.agents.executor._error_handler import (
    normalize_text,
    tool_signature,
    follow_up_like,
    build_stuck_error,
    ExecutionLoopState,
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


class TestNormalizeText:
    """Tests for normalize_text."""

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
        result = normalize_text(raw or "")
        assert result == expected


class TestToolSignature:
    """Tests for tool_signature."""

    def test_tool_signature_stable(self) -> None:
        sig1 = tool_signature("bash", '{"command": "ls", "timeout": 30}')
        sig2 = tool_signature("bash", '{"command": "ls", "timeout": 60}')
        assert sig1 == sig2, "signatures should ignore timeout"

    def test_tool_signature_invalid_json(self) -> None:
        sig = tool_signature("bash", "not-json")
        assert "bash" in sig


class TestFollowUpLike:
    """Tests for follow_up_like."""

    def test_follow_up_detected(self) -> None:
        assert follow_up_like("ok")
        assert follow_up_like("I don't know")
        assert follow_up_like("Got it, let me proceed")

    def test_non_follow_up(self) -> None:
        assert not follow_up_like("The file contains an error on line 42. Here is the fix.")


class TestStuckError:
    """Tests for build_stuck_error."""

    def test_build_stuck_error_format(self) -> None:
        from weebot.domain.models.plan import Step

        step = Step(id="step-1", description="Open browser", status="pending")
        result = build_stuck_error(
            step=step,
            reason="max step budget reached",
            recent_signatures=["goto:{}"],
            max_steps=50,
        )
        assert "step-1" in result
        assert "Open browser" in result
        assert "max step budget reached" in result
        assert "goto" in result


class TestExecutionLoopState:
    """Tests for ExecutionLoopState dataclass."""

    def test_record_tool_call_tracks_sig(self) -> None:
        state = ExecutionLoopState()
        sig = state.record_tool_call("bash", '{"command": "ls"}')
        assert sig
        assert state.last_tool_signature == sig

    def test_repeat_detection(self) -> None:
        state = ExecutionLoopState()
        state.record_tool_call("bash", '{"command": "ls"}')
        state.record_tool_call("bash", '{"command": "ls"}')
        assert state.same_tool_repeat_count == 1

    def test_follow_up_count(self) -> None:
        state = ExecutionLoopState()
        state.record_follow_up()
        state.record_follow_up()
        assert state.follow_up_count == 2
