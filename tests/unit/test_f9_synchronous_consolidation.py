"""F9 regression test: consolidation must be synchronous.

Verifies that MemoryCompactor.compact_session() applies all
transformations immediately in the same call — no deferred merge,
no background flush, no buffered merge window.

This is a conservative guarantee required by the paper's F9 finding:
delayed consolidation can lose temporal context.
"""
from __future__ import annotations

from weebot.application.services.memory_compactor import MemoryCompactor
from weebot.domain.models.event import (
    DoneEvent,
    MessageEvent,
    ToolEvent,
)
from weebot.domain.models.session import Session


class TestF9SynchronousConsolidation:
    """Consolidation must happen inline, not on a delay."""

    def test_compaction_returns_immediately(self) -> None:
        """compact_session() must return a Session synchronously."""
        session = Session(
            id="f9-test-1",
            events=[
                MessageEvent(role="user", message="Hello"),
                MessageEvent(role="assistant", message="Hi there!"),
                DoneEvent(),
            ],
        )
        compactor = MemoryCompactor()
        result = compactor.compact_session(session)
        # The result must be a Session (not a Future/coroutine/promise)
        assert result is not None
        assert isinstance(result, Session)
        assert result.id == "f9-test-1"

    def test_tool_events_compacted_inline(self) -> None:
        """Tool event truncation must happen during the call, not later."""
        long_output = "line\n" * 200
        session = Session(
            id="f9-test-2",
            events=[
                ToolEvent(
                    tool_call_id="tc1",
                    tool_name="bash",
                    function_name="bash",
                    function_args={"command": "ls"},
                    result=long_output,
                ),
                DoneEvent(),
            ],
        )
        compactor = MemoryCompactor(max_shell_lines=50, shell_tail_lines=10)
        result = compactor.compact_session(session)

        # The bash tool result must already be truncated
        tool_event = result.events[0]
        assert isinstance(tool_event, ToolEvent)
        assert tool_event.result is not None
        assert len(tool_event.result.splitlines()) <= 15  # 10 tail + header lines
        assert "[Output truncated from" in tool_event.result

    def test_screenshot_truncated_inline(self) -> None:
        """Screenshot truncation must happen during the call, not later."""
        huge_screenshot = "base64data" * 2000  # ~20k chars
        session = Session(
            id="f9-test-3",
            events=[
                ToolEvent(
                    tool_call_id="tc2",
                    tool_name="screen_capture",
                    function_name="screen_capture",
                    function_args={},
                    result=huge_screenshot,
                ),
                DoneEvent(),
            ],
        )
        compactor = MemoryCompactor(max_screenshot_chars=5000)
        result = compactor.compact_session(session)

        tool_event = result.events[0]
        assert isinstance(tool_event, ToolEvent)
        assert "[Screenshot compacted:" in (tool_event.result or "")

    def test_repeated_tool_results_deduplicated_inline(self) -> None:
        """Duplicate tool result dedup must happen during the call."""
        session = Session(
            id="f9-test-4",
            events=[
                ToolEvent(
                    tool_call_id=f"tc{i}",
                    tool_name="bash",
                    function_name="bash",
                    function_args={"command": "ls"},
                    result="same_output",
                )
                for i in range(5)
            ] + [DoneEvent()],
        )
        compactor = MemoryCompactor()
        result = compactor.compact_session(session)

        # The 5 identical events should be deduplicated to 1 with a count marker
        bash_events = [e for e in result.events if isinstance(e, ToolEvent)]
        assert len(bash_events) <= 2  # 1 deduped + possibly the DoneEvent
        assert any("Repeated" in (e.result or "") for e in bash_events)

    def test_constraint_preservation_before_compaction(self) -> None:
        """Constraints must be extracted BEFORE compaction, not after.

        This ordering ensures safety rules survive the truncation step.
        """
        session = Session(
            id="f9-test-5",
            events=[
                MessageEvent(role="user", message="Never delete /etc."),
                ToolEvent(
                    tool_call_id="tc",
                    tool_name="bash",
                    function_name="bash",
                    function_args={"command": "ls"},
                    result="some output",
                ),
                DoneEvent(),
            ],
        )
        compactor = MemoryCompactor(preserve_constraints=True)
        result = compactor.compact_session(session)

        # The constraints marker should appear at the beginning
        first_event = result.events[0]
        assert isinstance(first_event, MessageEvent)
        assert first_event.role == "assistant"
        assert "[CONSTRAINTS]" in first_event.message
