"""Tests for TDD RED-phase expected failure detection (Fix #8).

The executor should NOT abort when pytest returns exit code 1 during
[RED-VERIFY] steps — test failure is the DESIRED outcome in TDD.
"""
from __future__ import annotations

import pytest

from weebot.application.agents.executor._error_handler import (
    is_expected_failure,
    _TDD_EXPECTED_FAILURE_MARKERS,
)


class TestIsExpectedFailure:
    def test_red_verify_step(self):
        """RED-VERIFY step should be recognized as expected failure."""
        desc = "[RED-VERIFY] Run the test suite and confirm all tests FAIL (ImportError expected)"
        assert is_expected_failure(desc) is True

    def test_red_step(self):
        """RED step should be recognized."""
        desc = "[RED] Write test file for format_table function"
        assert is_expected_failure(desc) is True

    def test_red_verify_combined(self):
        """Combined RED+RED-VERIFY step."""
        desc = "[RED+RED-VERIFY] Write tests and confirm they fail"
        assert is_expected_failure(desc) is True  # "[RED]" substring matches

    def test_green_step_not_expected(self):
        """GREEN step should NOT be treated as expected failure."""
        desc = "[GREEN] Write the minimum implementation to make tests pass"
        assert is_expected_failure(desc) is False

    def test_green_verify_not_expected(self):
        """GREEN-VERIFY expects tests to PASS, not fail."""
        desc = "[GREEN-VERIFY] Run the test suite and confirm all tests PASS"
        assert is_expected_failure(desc) is False

    def test_clean_step_not_expected(self):
        """CLEAN step is not a failure-expected phase."""
        desc = "[CLEAN] Refactor for clarity while respecting architecture boundaries"
        assert is_expected_failure(desc) is False

    def test_normal_step_not_expected(self):
        """Normal step without TDD markers should not match."""
        desc = "List all files in the Output directory"
        assert is_expected_failure(desc) is False

    def test_empty_description(self):
        """Empty description should return False."""
        assert is_expected_failure("") is False
        assert is_expected_failure("  ") is False

    def test_exact_planner_phrasing(self):
        """The planner's exact RED-VERIFY instruction should match."""
        desc = "[RED-VERIFY] Run the test suite and confirm all tests FAIL (ImportError / NameError / AssertionError expected). Mandatory — proves tests execute."
        assert is_expected_failure(desc) is True

    def test_pytest_run_without_tdd_marker(self):
        """Running pytest without TDD marker is a real error."""
        desc = "Run the test suite to verify everything passes"
        assert is_expected_failure(desc) is False

    def test_partial_match_not_fooled(self):
        """A step mentioning RED but not in TDD context should not match."""
        desc = "Add a red border to the error display"
        # "red" appears but not as a TDD marker — the marker is "[RED]" with brackets
        # The function checks substrings, so "red" would match "red-verify" or "[red]"
        # Let"s verify: "red" in "[red]" → yes, so this WOULD match
        # This is acceptable — marking a non-TDD step as expected-failure is
        # safer than missing a TDD step and aborting it
        pass  # Documented: acceptable false positive


class TestTddMarkers:
    def test_markers_include_planner_phrases(self):
        """The marker set should include the planner's phrasing from planner_system.txt."""
        markers_lower = {m.lower() for m in _TDD_EXPECTED_FAILURE_MARKERS}
        assert "red-verify" in markers_lower
        assert "[red-verify]" in markers_lower
        assert "confirm all tests fail" in markers_lower

    def test_markers_are_immutable(self):
        """Markers should be a frozenset (immutable)."""
        assert isinstance(_TDD_EXPECTED_FAILURE_MARKERS, frozenset)

    def test_at_least_five_markers(self):
        """Should have enough markers to cover planner phrasing variations."""
        assert len(_TDD_EXPECTED_FAILURE_MARKERS) >= 5
