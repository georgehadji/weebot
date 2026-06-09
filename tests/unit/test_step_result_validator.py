"""Tests for Phase 3: StepResultValidator."""
import pytest

from weebot.application.services.step_result_validator import (
    StepResultValidator,
    ValidationResult,
)


@pytest.fixture
def validator():
    return StepResultValidator()


def test_empty_result_fails(validator):
    """result='' -> passed=False."""
    r = validator.validate(result="", step_description="Analyze data")
    assert not r.passed
    assert "empty" in r.reason


def test_null_string_fails(validator):
    """result='None' -> passed=False."""
    r = validator.validate(result="None", step_description="Analyze data")
    assert not r.passed
    assert "empty" in r.reason or "null" in r.reason


def test_undefined_fails(validator):
    """result='undefined' -> passed=False."""
    r = validator.validate(result="undefined", step_description="Fetch data")
    assert not r.passed


def test_too_short_fails(validator):
    """result='ok' (2 chars < 20) -> passed=False."""
    r = validator.validate(result="ok", step_description="Analyze data")
    assert not r.passed
    assert "too short" in r.reason


def test_identical_to_previous_fails(validator):
    """Same result twice -> passed=False."""
    result = "The analysis showed clear patterns in the data."
    r = validator.validate(
        result=result,
        step_description="Analyze data",
        previous_result=result,
    )
    assert not r.passed
    assert "identical" in r.reason


def test_good_result_passes(validator):
    """Meaningful result -> passed=True."""
    r = validator.validate(
        result="Step completed successfully with 42 items processed.",
        step_description="Process items",
    )
    assert r.passed


def test_quality_hint_references_step_description(validator):
    """Hint contains step description substring."""
    r = validator.validate(
        result="",
        step_description="Fetch API data",
    )
    assert "Fetch API data" in r.quality_hint


def test_barely_over_limit_passes(validator):
    """Result exactly at MIN_RESULT_CHARS passes."""
    result = "x" * 20
    r = validator.validate(result=result, step_description="Output")
    assert r.passed


def test_different_result_from_previous_passes(validator):
    """Different result from previous -> passes."""
    r = validator.validate(
        result="The analysis is complete with 30 data points.",
        step_description="Analyze",
        previous_result="Initial attempt had errors.",
    )
    assert r.passed


def test_n_a_fails(validator):
    """result='n/a' -> passed=False."""
    r = validator.validate(result="n/a", step_description="Check status")
    assert not r.passed


def test_empty_json_fails(validator):
    """result='{}' -> passed=False."""
    r = validator.validate(result="{}", step_description="Parse data")
    assert not r.passed
