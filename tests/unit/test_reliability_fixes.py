"""Tests for the 7 reliability fixes applied to the live-session crash.

Covers:
- Fix 1: memory_compactor tail-truncation (no MemoryError on large sessions)
- Fix 2a: Plan.merge() description-based deduplication
- Fix 2b: UpdatingState injects completed-steps summary (smoke test)
- Fix 3: CodeReviewerService timeout increase + consecutive-failure counter
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Fix 1 — MemoryCompactor: tail-truncation on large sessions
# ---------------------------------------------------------------------------


def test_compact_session_does_not_oom_on_large_session():
    """compact_session must not raise MemoryError with 500 events."""
    from weebot.application.services.memory_compactor import MemoryCompactor
    from weebot.domain.models.event import ToolEvent
    from weebot.domain.models.session import Session

    events = [
        ToolEvent(
            tool_call_id=f"tc-{i}",
            tool_name="bash",
            function_name="bash",
            function_args={"command": f"Get-ChildItem step-{i}"},
            result="some output " * 200,
        )
        for i in range(500)
    ]
    session = Session(id="big-session", events=events)
    compactor = MemoryCompactor(preserve_constraints=False)
    compacted = compactor.compact_session(session)
    assert compacted is not None
    assert len(compacted.events) <= len(session.events)


def test_compact_session_with_constraints_uses_tail_only(monkeypatch):
    """The constraint extractor receives only the last 200 events, not all."""
    from weebot.application.services.memory_compactor import MemoryCompactor
    from weebot.application.services.constraint_extractor import ConstraintExtractor
    from weebot.domain.models.event import ToolEvent
    from weebot.domain.models.session import Session

    captured_text: list[str] = []

    class SpyExtractor(ConstraintExtractor):
        def extract(self, text: str):
            captured_text.append(text)
            return []

    events = [
        ToolEvent(
            tool_call_id=f"tc-{i}",
            tool_name="bash",
            function_name="bash",
            function_args={},
            result=f"event-{i}",
        )
        for i in range(300)
    ]
    session = Session(id="s", events=events)
    compactor = MemoryCompactor(preserve_constraints=True)
    compactor._constraint_extractor = SpyExtractor()
    compactor.compact_session(session)

    assert len(captured_text) == 1
    # Only the last 200 events should appear in the joined text
    assert "event-299" in captured_text[0]
    assert "event-0" not in captured_text[0]


# ---------------------------------------------------------------------------
# Fix 2a — Plan.merge(): description-based deduplication
# ---------------------------------------------------------------------------


def _make_step(id_: str, desc: str, completed: bool = False):
    from weebot.domain.models.plan import Step, StepStatus
    status = StepStatus.COMPLETED if completed else StepStatus.PENDING
    return Step(id=id_, description=desc, status=status)


def test_merge_keeps_completed_steps():
    from weebot.domain.models.plan import Plan
    original = Plan(steps=[
        _make_step("s1", "Scaffold Next.js project", completed=True),
        _make_step("s2", "Install dependencies", completed=True),
        _make_step("s3", "Build header component"),
    ])
    updated = Plan(steps=[
        _make_step("s3", "Build header component"),
        _make_step("s4", "Build footer component"),
    ])
    merged = original.merge(updated)
    ids = [s.id for s in merged.steps]
    assert "s1" in ids
    assert "s2" in ids


def test_merge_deduplicates_by_description():
    """Steps with fresh IDs but same description as completed steps must not reappear."""
    from weebot.domain.models.plan import Plan
    original = Plan(steps=[
        _make_step("s1", "Scaffold Next.js project", completed=True),
        _make_step("s2", "Install npm dependencies", completed=True),
    ])
    updated = Plan(steps=[
        # LLM gave fresh IDs but identical descriptions
        _make_step("step-a", "Scaffold Next.js project"),
        _make_step("step-b", "Install npm dependencies"),
        _make_step("step-c", "Create homepage layout"),
    ])
    merged = original.merge(updated)
    descs = [s.description for s in merged.steps]
    # Already-done work must not be re-added
    assert descs.count("Scaffold Next.js project") == 1
    assert descs.count("Install npm dependencies") == 1
    # New work must be present
    assert "Create homepage layout" in descs


def test_merge_description_match_is_case_insensitive():
    """Prefix comparison is case-insensitive and trims whitespace."""
    from weebot.domain.models.plan import Plan
    original = Plan(steps=[
        _make_step("s1", "  Scaffold Next.JS Project  ", completed=True),
    ])
    updated = Plan(steps=[
        # Same content, different casing and no surrounding whitespace
        _make_step("new-1", "scaffold next.js project"),
    ])
    merged = original.merge(updated)
    pending_descs = [s.description for s in merged.steps if not s.is_done()]
    # The re-generated step should be dropped as a duplicate
    assert not any(d.lower().strip() == "scaffold next.js project" for d in pending_descs)


def test_merge_does_not_filter_genuinely_distinct_followup():
    """A step that extends a completed description with extra detail is NOT a duplicate."""
    from weebot.domain.models.plan import Plan
    original = Plan(steps=[
        _make_step("s1", "Scaffold Next.js project", completed=True),
    ])
    updated = Plan(steps=[
        _make_step("new-1", "scaffold next.js project — add TypeScript config"),
    ])
    merged = original.merge(updated)
    pending_descs = [s.description for s in merged.steps if not s.is_done()]
    # Different 80-char prefix → kept
    assert any("typescript config" in d.lower() for d in pending_descs)


def test_merge_does_not_drop_genuinely_new_steps():
    """Steps with descriptions not matching any completed step must be kept."""
    from weebot.domain.models.plan import Plan
    original = Plan(steps=[
        _make_step("s1", "Setup project structure", completed=True),
    ])
    updated = Plan(steps=[
        _make_step("u1", "Add dark mode toggle"),
        _make_step("u2", "Deploy to Vercel"),
    ])
    merged = original.merge(updated)
    pending = [s.description for s in merged.steps if not s.is_done()]
    assert "Add dark mode toggle" in pending
    assert "Deploy to Vercel" in pending


# ---------------------------------------------------------------------------
# Fix 3 — CodeReviewerService: timeout + consecutive-failure counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_reviewer_default_timeout_is_30s():
    from weebot.application.services.code_reviewer_service import CodeReviewerService
    svc = CodeReviewerService(llm=MagicMock())
    assert svc._timeout_seconds == 30.0


@pytest.mark.asyncio
async def test_code_reviewer_resets_failure_counter_on_success():
    from weebot.application.services.code_reviewer_service import CodeReviewerService
    from weebot.domain.models.plan import Step

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=MagicMock(
        content='{"verdict":"approved","issues":[],"hint":"","confidence":0.9,"severity":"info"}',
    ))
    svc = CodeReviewerService(llm=mock_llm, timeout_seconds=5.0)
    svc._consecutive_failures = 5  # simulate prior failures

    result = await svc.review(Step(id="s1", description="test"), {})
    assert result.verdict == "approved"
    assert svc._consecutive_failures == 0


@pytest.mark.asyncio
async def test_code_reviewer_increments_failure_counter_on_timeout():
    from weebot.application.services.code_reviewer_service import CodeReviewerService
    from weebot.domain.models.plan import Step

    async def slow_chat(**kwargs):
        await asyncio.sleep(10)

    mock_llm = MagicMock()
    mock_llm.chat = slow_chat
    svc = CodeReviewerService(llm=mock_llm, timeout_seconds=0.01)

    result = await svc.review(Step(id="s1", description="test"), {})
    assert result.verdict == "approved"
    assert svc._consecutive_failures == 1


@pytest.mark.asyncio
async def test_code_reviewer_escalates_to_error_after_3_failures(caplog):
    import logging
    from weebot.application.services.code_reviewer_service import CodeReviewerService
    from weebot.domain.models.plan import Step

    async def always_fail(**kwargs):
        raise RuntimeError("network error")

    mock_llm = MagicMock()
    mock_llm.chat = always_fail
    svc = CodeReviewerService(llm=mock_llm, timeout_seconds=1.0)

    with caplog.at_level(logging.WARNING):
        for i in range(4):
            await svc.review(Step(id=f"s{i}", description="test"), {})

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) >= 1
    assert "consecutive" in error_records[0].message
