"""Tests for Phase 3: CodeReviewerService."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from weebot.application.services.code_reviewer_service import CodeReviewerService
from weebot.domain.models.code_review import CodeReviewResult
from weebot.domain.models.plan import Step


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def sample_step():
    return Step(id="step-1", description="Implement a function to sort data")


@pytest.fixture
def service(mock_llm):
    return CodeReviewerService(llm=mock_llm, timeout_seconds=5)


@pytest.fixture
def review_context():
    return {
        "task": "Build a sorting algorithm",
        "plan_title": "Sorting implementation",
        "completed_steps": 2,
        "step_events": [
            {"type": "tool", "tool_name": "file_editor", "tool_input": "def sort(arr):"},
        ],
    }


@pytest.mark.asyncio
async def test_approved_verdict_returned(service, mock_llm, sample_step, review_context):
    """LLM returns valid JSON approved."""
    mock_llm.chat.return_value = MagicMock(
        content='{"verdict": "approved", "issues": [], "hint": "", "confidence": 0.9, "severity": "info"}'
    )
    result = await service.review(sample_step, review_context)
    assert result.verdict == "approved"
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_revise_verdict_with_hint(service, mock_llm, sample_step, review_context):
    """LLM returns revise with hint."""
    mock_llm.chat.return_value = MagicMock(
        content='{"verdict": "revise", "issues": ["Missing error handling"], "hint": "Add try/except", "confidence": 0.7, "severity": "warning"}'
    )
    result = await service.review(sample_step, review_context)
    assert result.verdict == "revise"
    assert "Missing error handling" in result.issues
    assert result.hint == "Add try/except"


@pytest.mark.asyncio
async def test_reject_verdict_with_issues(service, mock_llm, sample_step, review_context):
    """LLM returns reject with issues."""
    mock_llm.chat.return_value = MagicMock(
        content='{"verdict": "reject", "issues": ["Security vulnerability"], "hint": "", "confidence": 0.95, "severity": "error"}'
    )
    result = await service.review(sample_step, review_context)
    assert result.verdict == "reject"
    assert result.severity == "error"


@pytest.mark.asyncio
async def test_timeout_returns_approved(service, mock_llm, sample_step, review_context):
    """Timeout returns approved default."""
    import asyncio
    mock_llm.chat.side_effect = asyncio.TimeoutError()
    result = await service.review(sample_step, review_context)
    assert result.verdict == "approved"


@pytest.mark.asyncio
async def test_json_parse_failure_returns_approved(service, mock_llm, sample_step, review_context):
    """Malformed JSON returns approved."""
    mock_llm.chat.return_value = MagicMock(content="not valid json")
    result = await service.review(sample_step, review_context)
    assert result.verdict == "approved"


@pytest.mark.asyncio
async def test_markdown_fence_stripped(service, mock_llm, sample_step, review_context):
    """JSON in ```json``` fences is stripped correctly."""
    mock_llm.chat.return_value = MagicMock(
        content="```json\n{\"verdict\": \"approved\", \"issues\": [], \"hint\": \"\", \"confidence\": 1.0, \"severity\": \"info\"}\n```"
    )
    result = await service.review(sample_step, review_context)
    assert result.verdict == "approved"


@pytest.mark.asyncio
async def test_confidence_clamped_to_range(service, mock_llm, sample_step, review_context):
    """Confidence of 1.5 is clamped to 1.0 (manual clamp before Pydantic construction)."""
    mock_llm.chat.return_value = MagicMock(
        content='{"verdict": "approved", "issues": [], "hint": "", "confidence": 1.5, "severity": "info"}'
    )
    result = await service.review(sample_step, review_context)
    assert result.confidence == 1.0
    assert result.verdict == "approved"  # Should succeed, not fail-open


@pytest.mark.asyncio
async def test_confidence_below_zero_clamped(service, mock_llm, sample_step, review_context):
    """Confidence of -0.5 is clamped to 0.0."""
    mock_llm.chat.return_value = MagicMock(
        content='{"verdict": "approved", "issues": [], "hint": "", "confidence": -0.5, "severity": "info"}'
    )
    result = await service.review(sample_step, review_context)
    assert result.confidence == 0.0
    assert result.verdict == "approved"


@pytest.mark.asyncio
async def test_one_liner_fence_stripped(service, mock_llm, sample_step, review_context):
    """One-liner ```json {...}``` fence is stripped."""
    mock_llm.chat.return_value = MagicMock(
        content='```json {"verdict": "approved", "issues": [], "hint": "", "confidence": 1.0, "severity": "info"}```'
    )
    result = await service.review(sample_step, review_context)
    assert result.verdict == "approved"


@pytest.mark.asyncio
async def test_empty_step_result_handled(service, mock_llm, review_context):
    """step.result = None — no crash."""
    step = Step(id="s1", description="Write code", result=None)
    mock_llm.chat.return_value = MagicMock(
        content='{"verdict": "approved", "issues": [], "hint": "", "confidence": 1.0, "severity": "info"}'
    )
    result = await service.review(step, review_context)
    assert result.verdict == "approved"


def test_summary_no_issues():
    """summary property with no issues."""
    r = CodeReviewResult(step_id="s1", verdict="approved")
    assert "No issues found" in r.summary


def test_summary_with_issues():
    """summary property with issues."""
    r = CodeReviewResult(step_id="s1", verdict="revise", issues=["Bug A", "Bug B"])
    assert "Bug A" in r.summary
    assert "Bug B" in r.summary


def test_is_actionable():
    """is_actionable True for revise/reject."""
    assert CodeReviewResult(step_id="s1", verdict="revise").is_actionable
    assert CodeReviewResult(step_id="s1", verdict="reject").is_actionable
    assert not CodeReviewResult(step_id="s1", verdict="approved").is_actionable


# ---------------------------------------------------------------------------
# Fix 5: _render_tool_events prioritization
# ---------------------------------------------------------------------------

class TestRenderToolEventsPrioritization:
    """Tests for Fix 5: prioritized tool event rendering."""

    def test_render_tool_events_prioritizes_writes(self, service, mock_llm, review_context):
        """Write operations (file_editor) appear even when outnumbered by read-only tools."""
        # Use tool names NOT in WRITE_TOOLS for non-significant events
        events = [
            {"type": "tool", "tool_name": "list_directory", "tool_input": f"Explore dir_{i}"}
            for i in range(40)
        ] + [
            {"type": "tool", "tool_name": "file_editor", "tool_input": f"write file_{i}.py"}
            for i in range(5)
        ] + [
            {"type": "tool", "tool_name": "web_search", "tool_input": f"Search query {i}"}
            for i in range(5)
        ]
        rendered = service._render_tool_events(events, max_events=10)
        assert "file_editor" in rendered

    def test_render_tool_events_returns_no_tools(self, service):
        """Empty events list returns placeholder."""
        rendered = service._render_tool_events([], max_events=10)
        assert rendered == "(no tool calls)"

    def test_render_tool_events_filters_non_tool_events(self, service):
        """Non-dict or non-tool events are skipped."""
        events = [
            {"type": "thought", "content": "thinking..."},
            {"type": "tool", "tool_name": "bash", "tool_input": "echo hi"},
        ]
        rendered = service._render_tool_events(events, max_events=10)
        assert "echo hi" in rendered
        assert "thinking" not in rendered


# ---------------------------------------------------------------------------
# Fix 6: retry on parse error
# ---------------------------------------------------------------------------

class TestCodeReviewerRetry:
    """Tests for Fix 6: retry once on JSON parse error before auto-approving."""

    @pytest.mark.asyncio
    async def test_retry_on_parse_error(self, mock_llm, sample_step, review_context):
        """First call returns bad JSON, second succeeds."""
        mock_llm.chat.side_effect = [
            MagicMock(content="not valid json"),
            MagicMock(content='{"verdict": "approved", "issues": [], "hint": "", "confidence": 1.0, "severity": "info"}'),
        ]
        svc = CodeReviewerService(llm=mock_llm, timeout_seconds=5)
        result = await svc.review(sample_step, review_context)
        assert result.verdict == "approved"
        assert mock_llm.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_auto_approve_after_two_parse_failures(self, mock_llm, sample_step, review_context):
        """Both attempts fail JSON parse — auto-approve."""
        mock_llm.chat.side_effect = [
            MagicMock(content="bad json 1"),
            MagicMock(content="bad json 2"),
        ]
        svc = CodeReviewerService(llm=mock_llm, timeout_seconds=5)
        result = await svc.review(sample_step, review_context)
        assert result.verdict == "approved"
        assert mock_llm.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_llm_error_returns_approved_immediately(self, mock_llm, sample_step, review_context):
        """LLM error (timeout) returns approved immediately without retry."""
        import asyncio
        mock_llm.chat.side_effect = asyncio.TimeoutError()
        svc = CodeReviewerService(llm=mock_llm, timeout_seconds=5)
        result = await svc.review(sample_step, review_context)
        assert result.verdict == "approved"
        assert mock_llm.chat.call_count == 1
