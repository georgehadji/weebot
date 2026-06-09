"""Tests for Phase 5: ReviewingState."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.flows.states.reviewing import ReviewingState
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.plan import Plan, Step, StepStatus


@pytest.fixture
def mock_reviewer():
    reviewer = AsyncMock()
    reviewer.review.return_value = CodeReviewResult(
        step_id="step-1",
        verdict="approved",
    )
    return reviewer


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx._plan = Plan(
        title="Test plan",
        steps=[
            Step(id="step-1", description="Write code"),
            Step(id="step-2", description="Test code"),
        ],
    )
    ctx._code_reviewer = None
    return ctx


@pytest.mark.asyncio
async def test_no_reviewer_falls_through(mock_context):
    """reviewer=None sets ExecutingState immediately."""
    state = ReviewingState(step=Step(id="s1", description="x"), reviewer=None)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    # No ThoughtEvent since reviewer is None
    assert len(events) == 0
    mock_context.set_state.assert_called_once()


@pytest.mark.asyncio
async def test_approved_advances_to_next_step(mock_context, mock_reviewer):
    """approved verdict -> ExecutingState."""
    step = Step(id="step-1", description="Write code")
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    assert len(events) == 1  # ThoughtEvent
    # Should have set ExecutingState
    assert mock_context.set_state.called


@pytest.mark.asyncio
async def test_revise_injects_hint_and_retries(mock_context, mock_reviewer):
    """revise verdict -> hint injected, retry_count+1, status=PENDING."""
    mock_reviewer.review.return_value = CodeReviewResult(
        step_id="step-1",
        verdict="revise",
        hint="Add input validation",
    )
    step = Step(id="step-1", description="Write code")
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    # Check the plan was updated
    updated_step = mock_context._plan.get_next_step()
    assert "Code review hint" in updated_step.description
    assert updated_step.retry_count == 1


@pytest.mark.asyncio
async def test_revise_without_hint_no_bracket(mock_context, mock_reviewer):
    """revise with empty hint -> description unchanged."""
    mock_reviewer.review.return_value = CodeReviewResult(
        step_id="step-1",
        verdict="revise",
        hint="",
    )
    step = Step(id="step-1", description="Write code", retry_count=0)
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    # The step should have retry_count incremented but no hint appended
    updated_plan = mock_context._plan
    revised_step = updated_plan.get_next_step()
    if revised_step:
        assert "[Code review hint" not in revised_step.description


@pytest.mark.asyncio
async def test_reject_marks_step_failed(mock_context, mock_reviewer):
    """reject verdict -> step FAILED, UpdatingState."""
    mock_reviewer.review.return_value = CodeReviewResult(
        step_id="step-1",
        verdict="reject",
        issues=["Unrecoverable issue"],
    )
    step = Step(id="step-1", description="Write code")
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    # Should have transitioned (set_state was called)
    assert mock_context.set_state.called


@pytest.mark.asyncio
async def test_retry_cap_prevents_loop(mock_context, mock_reviewer):
    """retry_count >= _MAX_REVIEW_RETRIES -> auto approved."""
    step = Step(id="step-1", description="Write code", retry_count=2)
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    # Reviewer should NOT have been called
    mock_reviewer.review.assert_not_called()


@pytest.mark.asyncio
async def test_thought_event_yielded(mock_context, mock_reviewer):
    """ThoughtEvent is always yielded on review."""
    step = Step(id="step-1", description="Write code")
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    assert len(events) == 1
    from weebot.domain.models.event import ThoughtEvent
    assert isinstance(events[0], ThoughtEvent)


@pytest.mark.asyncio
async def test_no_plan_falls_through(mock_context, mock_reviewer):
    """context._plan = None -> graceful fallthrough."""
    mock_context._plan = None
    step = Step(id="step-1", description="Write code")
    state = ReviewingState(step=step, reviewer=mock_reviewer)
    gen = state.execute(mock_context, "test prompt")
    events = [e async for e in gen]
    assert len(events) == 0
    mock_context.set_state.assert_called_once()


def test_is_code_step_helper():
    """_is_code_step detects code-producing steps."""
    from weebot.application.flows.states.executing import _is_code_step
    assert _is_code_step(Step(id="s1", description="Implement sorting"))
    assert _is_code_step(Step(id="s2", description="Write a Python script"))
    assert _is_code_step(Step(id="s3", description="Fix bug in parser"))
    assert not _is_code_step(Step(id="s4", description="Search for documentation"))
    assert not _is_code_step(Step(id="s5", description="Read the file"))
