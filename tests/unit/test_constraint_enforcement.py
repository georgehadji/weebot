"""Tests for Enhancement 1 — ConstraintExtractor.check_step() (S3 fix)."""
from __future__ import annotations

import pytest

from weebot.application.services.constraint_extractor import Constraint, ConstraintExtractor


class TestConstraintExtractorCheckStep:
    def _extractor(self):
        return ConstraintExtractor()

    def test_prohibit_delete_flagged(self):
        e = self._extractor()
        constraints = e.extract("DO NOT delete the user pool")
        violations = e.check_step("Delete user pool entries", constraints)
        assert len(violations) == 1

    def test_safety_constraint_flagged(self):
        e = self._extractor()
        constraints = e.extract("never expose API keys in logs")
        violations = e.check_step("Print API key to logs for debugging", constraints)
        assert len(violations) >= 1

    def test_unrelated_step_passes(self):
        e = self._extractor()
        constraints = e.extract("do not touch billing module")
        violations = e.check_step("Update README with new instructions", constraints)
        assert violations == []

    def test_positive_requirements_skipped(self):
        e = self._extractor()
        # Positive constraints (priority 3) should not be checked by check_step
        constraints = e.extract("always add tests for new functions")
        violations = e.check_step("Delete test file", constraints)
        # Positive requirements are not enforced here
        assert violations == []

    def test_empty_constraints_passes(self):
        e = self._extractor()
        violations = e.check_step("Do anything at all", [])
        assert violations == []

    def test_never_constraint_flagged(self):
        e = self._extractor()
        constraints = e.extract("Never modify the production database directly")
        violations = e.check_step("Modify production database directly", constraints)
        assert len(violations) >= 1

    def test_must_not_constraint_flagged(self):
        e = self._extractor()
        constraints = e.extract("must not overwrite existing backups")
        violations = e.check_step("overwrite existing backups with new data", constraints)
        assert len(violations) >= 1
