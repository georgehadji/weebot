"""Unit tests for composite tool domain models."""
from __future__ import annotations

from weebot.domain.models.composite_tool import (
    CompositeToolSpec,
    SubToolCall,
    CompositeResult,
)


class TestCompositeToolSpec:
    """Serialization and defaults."""

    def test_spec_serializes(self):
        spec = CompositeToolSpec(
            name="analyze_and_edit",
            description="Analyze and edit a file",
            sub_tools=[
                SubToolCall(
                    tool_name="file_view",
                    arguments={"path": "${path}"},
                    capture_output_as="content",
                ),
            ],
            hidden_atomic_tools=["file_editor"],
            transaction_policy="all_or_none",
        )
        data = spec.model_dump()
        assert data["name"] == "analyze_and_edit"
        assert data["hidden_atomic_tools"] == ["file_editor"]
        assert data["transaction_policy"] == "all_or_none"

    def test_default_transaction_policy_is_best_effort(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[],
        )
        assert spec.transaction_policy == "best_effort"

    def test_default_hidden_atomic_tools_is_empty(self):
        spec = CompositeToolSpec(
            name="demo",
            description="Demo",
            sub_tools=[],
        )
        assert spec.hidden_atomic_tools == []


class TestCompositeResult:
    """Composite result model."""

    def test_result_serializes(self):
        result = CompositeResult(
            success=True,
            summary="All steps completed",
            sub_results=[{"tool": "bash", "success": True}],
        )
        data = result.model_dump()
        assert data["success"] is True
        assert data["aborted_after_failure"] is False
