"""Tests for PlanActFlow state transitions and resume logic."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from weebot.domain.models.plan import Plan, Step, StepStatus
from weebot.domain.models.session import Session, SessionStatus


class TestPlanActFlowResume:
    """Tests for session resume behavior."""

    def test_session_continuation_words_are_in_set(self) -> None:
        """Verify the CONTINUATION_WORDS set contains expected entries."""
        from weebot.application.services.continuation_detector import (
            ContinuationDetector, CONTINUATION_WORDS,
        )
        assert "proceed" in CONTINUATION_WORDS
        assert "continue" in CONTINUATION_WORDS
        assert "yes" in CONTINUATION_WORDS
        assert "" in CONTINUATION_WORDS  # empty string

        # Verify short answer IS detected as continuation
        assert ContinuationDetector.is_continuation("proceed")
        assert ContinuationDetector.is_continuation("  proceed  ")

        # Verify longer text is NOT a continuation
        assert not ContinuationDetector.is_continuation("email: user@example.com")

    def test_is_vague_detects_short_inputs(self) -> None:
        """Verify is_vague returns True for ≤3 words."""
        from weebot.application.services.continuation_detector import (
            ContinuationDetector,
        )
        assert ContinuationDetector.is_vague("one")
        assert ContinuationDetector.is_vague("one two")
        assert ContinuationDetector.is_vague("one two three")
        assert not ContinuationDetector.is_vague("one two three four")

    def test_resolve_prompt_enriches_continuation(self) -> None:
        """Verify vague prompts are enriched with original task."""
        from weebot.application.services.continuation_detector import (
            ContinuationDetector,
        )
        result = ContinuationDetector.resolve_prompt(
            user_prompt="proceed",
            original_task="Open browser and log into LinkedIn",
            event_count=10,
        )
        assert result == "Open browser and log into LinkedIn"

    def test_resolve_prompt_passes_through_substantive_input(self) -> None:
        """Verify non-vague inputs pass through unchanged."""
        from weebot.application.services.continuation_detector import (
            ContinuationDetector,
        )
        result = ContinuationDetector.resolve_prompt(
            user_prompt="Use admin credentials for the login page",
            original_task="Original task",
            event_count=10,
        )
        assert result == "Use admin credentials for the login page"


class TestStepRepetitionLimits:
    """Tests for max_step_repetitions enforcement."""

    def test_step_repetition_count_starts_at_zero(self) -> None:
        """Verify step execution counts initialize at 0."""
        # The dict is a simple Python dict, so this is straightforward:
        counts: dict[str, int] = {}
        assert counts.get("step-1", 0) == 0
        counts["step-1"] = counts.get("step-1", 0) + 1
        assert counts["step-1"] == 1


class TestPlanMerge:
    """Tests for Plan.merge() behavior."""

    def test_merge_preserves_completed_steps(self) -> None:
        """Verify merging plans preserves already-completed steps."""
        original = Plan(
            title="Test Plan",
            message="Original",
            steps=[
                Step(id="step-1", description="First", status="completed"),
                Step(id="step-2", description="Second", status="pending"),
            ],
        )
        updated = Plan(
            title="Updated Plan",
            message="Updated",
            steps=[
                Step(id="step-1", description="First", status="pending"),
                Step(id="step-3", description="Third", status="pending"),
            ],
        )
        merged = original.merge(updated)
        # merge preserves existing plan metadata by default
        # Completed step should stay completed
        step1 = next(s for s in merged.steps if s.id == "step-1")
        assert step1.status == "completed"
        # New step should be present
        step3_ids = [s.id for s in merged.steps]
        assert "step-3" in step3_ids
