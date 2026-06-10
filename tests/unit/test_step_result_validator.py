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


# ── Fix 2: step_events defence-in-depth tests ──────────────────────

def _file_created_event(tool_name="file_editor", result="Created /tmp/foo.md (2746 chars)"):
    """Helper: create a ToolEvent representing successful file creation."""
    from weebot.domain.models.event import ToolEvent, ToolStatus
    return ToolEvent(
        type="tool",
        tool_call_id="call-1",
        tool_name=tool_name,
        function_name=tool_name,
        status=ToolStatus.CALLED,
        result=result,
    )


def _assistant_message_event(message="Step completed."):
    """Helper: create a MessageEvent from the assistant."""
    from weebot.domain.models.event import MessageEvent
    return MessageEvent(
        type="message",
        role="assistant",
        message=message,
    )


def _tool_event_no_creation(tool_name="bash", result="some output"):
    """Helper: create a ToolEvent for a non-file-creation tool."""
    from weebot.domain.models.event import ToolEvent, ToolStatus
    return ToolEvent(
        type="tool",
        tool_call_id="call-1",
        tool_name=tool_name,
        function_name=tool_name,
        status=ToolStatus.CALLED,
        result=result,
    )


def test_file_creation_bypasses_empty_result(validator):
    """result=None + file_editor 'Created' event -> passed=True."""
    r = validator.validate(
        result=None,
        step_description="Create a file",
        step_events=[_file_created_event()],
    )
    assert r.passed


def test_file_creation_wrote_bypasses_empty(validator):
    """result='' + file_editor 'Wrote' event -> passed=True."""
    r = validator.validate(
        result="",
        step_description="Write to file",
        step_events=[_file_created_event(result="Wrote /tmp/out.txt (150 chars)")],
    )
    assert r.passed


def test_file_creation_updated_bypasses_empty(validator):
    """result='' + edit_file 'Updated' event -> passed=True."""
    r = validator.validate(
        result="",
        step_description="Edit file",
        step_events=[_file_created_event(tool_name="edit_file", result="Updated /tmp/conf.yaml (89 chars)")],
    )
    assert r.passed


def test_file_creation_no_result_text_falls_through(validator):
    """file_editor event with empty result -> falls through to normal check."""
    r = validator.validate(
        result=None,
        step_description="Create a file",
        step_events=[_file_created_event(result="")],
    )
    assert not r.passed


def test_non_file_tool_does_not_bypass(validator):
    """bash tool event with output does NOT bypass empty-result check."""
    r = validator.validate(
        result=None,
        step_description="Run command",
        step_events=[_tool_event_no_creation()],
    )
    assert not r.passed


def test_empty_step_events_list_falls_through(validator):
    """Empty step_events list -> falls through to normal empty check."""
    r = validator.validate(
        result=None,
        step_description="Do something",
        step_events=[],
    )
    assert not r.passed


def test_step_events_default_none_unchanged(validator):
    """step_events=None (default) + result='some output' -> passed=True."""
    r = validator.validate(
        result="The analysis found 42 patterns in the dataset.",
        step_description="Analyze data",
    )
    assert r.passed


def test_multiple_events_first_is_file_creation(validator):
    """First event is file_editor, second is bash — file creation wins."""
    r = validator.validate(
        result="",
        step_description="Create then verify",
        step_events=[
            _file_created_event(),
            _tool_event_no_creation(tool_name="bash", result="File exists check"),
        ],
    )
    assert r.passed
