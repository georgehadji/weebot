"""Tests for enhanced ToolResult with structured JSON output and metadata.

Phase 2 Deliverable: 8+ tests for ToolResult enhancement
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from weebot.tools.base import ToolResult, BaseTool, ToolCollection


class TestToolResultEnhanced:
    """Tests for enhanced ToolResult functionality."""

    def test_default_success_result(self):
        """Default result is successful."""
        result = ToolResult(output="Success")
        
        assert result.success is True
        assert result.is_error is False
        assert result.error is None

    def test_error_result_detection(self):
        """Result with error is not successful."""
        result = ToolResult(output="", error="Something failed")
        
        assert result.success is False
        assert result.is_error is True

    def test_success_result_factory(self):
        """success_result factory creates successful result."""
        result = ToolResult.success_result(
            output="Done",
            data={"key": "value"},
            execution_time_ms=100.0
        )
        
        assert result.success is True
        assert result.output == "Done"
        assert result.data == {"key": "value"}
        assert result.metadata["execution_time_ms"] == 100.0

    def test_error_result_factory(self):
        """error_result factory creates error result."""
        result = ToolResult.error_result(
            error="Failed",
            output="Partial output",
            execution_time_ms=50.0
        )
        
        assert result.success is False
        assert result.error == "Failed"
        assert result.output == "Partial output"
        assert result.metadata["execution_time_ms"] == 50.0

    def test_to_dict_serialization(self):
        """to_dict returns serializable dictionary."""
        result = ToolResult.success_result(
            output="Test",
            data={"nested": {"value": 123}},
            execution_time_ms=42.0
        )
        
        d = result.to_dict()
        
        assert d["output"] == "Test"
        assert d["success"] is True
        assert d["data"]["nested"]["value"] == 123
        assert d["metadata"]["execution_time_ms"] == 42.0
        assert d["has_image"] is False

    def test_backward_compatibility_str(self):
        """String representation is backward compatible."""
        success = ToolResult(output="Success")
        error = ToolResult(error="Failed")
        
        assert str(success) == "Success"
        assert str(error) == "ERROR: Failed"

    def test_metadata_storage(self):
        """Metadata can store various tracking fields."""
        result = ToolResult.success_result(
            execution_time_ms=150.0,
            retry_count=2,
            circuit_breaker_state="CLOSED",
            tool_name="test_tool"
        )
        
        assert result.metadata["execution_time_ms"] == 150.0
        assert result.metadata["retry_count"] == 2
        assert result.metadata["circuit_breaker_state"] == "CLOSED"
        assert result.metadata["tool_name"] == "test_tool"

    def test_post_init_error_sync(self):
        """Post-init syncs success and error fields."""
        # Error set, success should be False
        result1 = ToolResult(output="", error="Failed", success=True)
        assert result1.success is False
        
        # Success False, error should be set
        result2 = ToolResult(output="", success=False)
        assert result2.error is not None


class TestToolResultWithImage:
    """Tests for ToolResult with image support."""

    def test_image_presence(self):
        """to_dict indicates image presence."""
        result = ToolResult(output="Image result", base64_image="base64data")
        
        d = result.to_dict()
        assert d["has_image"] is True

    def test_no_image(self):
        """to_dict correctly reports no image."""
        result = ToolResult(output="Text result")
        
        d = result.to_dict()
        assert d["has_image"] is False


class TestToolCollectionMetadata:
    """Tests for ToolCollection with metadata tracking."""

    class MockTool(BaseTool):
        """Mock tool for testing."""
        name: str = "mock_tool"
        description: str = "A mock tool"
        parameters: dict = {}
        
        async def execute(self, **kwargs) -> ToolResult:
            return ToolResult.success_result(
                output="Mock result",
                data={"input": kwargs}
            )

    @pytest.mark.asyncio
    async def test_execution_metadata_added(self):
        """ToolCollection adds execution metadata."""
        tool = self.MockTool()
        collection = ToolCollection(tool)
        
        result = await collection.execute("mock_tool")
        
        assert "execution_time_ms" in result.metadata
        assert "retry_count" in result.metadata
        assert result.metadata["retry_count"] == 0
        assert result.metadata["tool_name"] == "mock_tool"

    @pytest.mark.asyncio
    async def test_unknown_tool_metadata(self):
        """Unknown tool error includes metadata."""
        collection = ToolCollection()
        
        result = await collection.execute("unknown_tool")
        
        assert result.success is False
        assert "Unknown tool" in result.error
        assert result.metadata["execution_time_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """ToolCollection retries on failure."""
        failing_tool = AsyncMock(spec=BaseTool)
        failing_tool.name = "failing_tool"
        failing_tool.execute = AsyncMock(side_effect=Exception("Always fails"))
        
        collection = ToolCollection(failing_tool)
        
        result = await collection.execute("failing_tool", _max_retries=2)
        
        assert result.success is False
        assert result.metadata["retry_count"] == 2
        # Should be called 3 times (initial + 2 retries)
        assert failing_tool.execute.call_count == 3


class TestToolResultDataField:
    """Tests for structured data field."""

    def test_complex_nested_data(self):
        """Data field supports complex nested structures."""
        complex_data = {
            "users": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"}
            ],
            "metadata": {
                "count": 2,
                "page": 1
            },
            "timestamp": "2026-01-01T00:00:00Z"
        }
        
        result = ToolResult.success_result(data=complex_data)
        
        assert result.data["users"][0]["name"] == "Alice"
        assert result.data["metadata"]["count"] == 2

    def test_empty_data(self):
        """Empty data is handled correctly."""
        result = ToolResult.success_result(output="No data")
        
        assert result.data == {}

    def test_data_with_none_values(self):
        """Data can contain None values."""
        result = ToolResult.success_result(
            data={"value": None, "other": "present"}
        )
        
        assert result.data["value"] is None
        assert result.data["other"] == "present"


class TestToolResultBackwardCompatibility:
    """Tests ensuring backward compatibility with legacy code."""

    def test_legacy_constructor(self):
        """Legacy constructor style still works."""
        # Old style: ToolResult(output, error)
        result = ToolResult("output text", "error message")
        
        assert result.output == "output text"
        assert result.error == "error message"

    def test_legacy_is_error_property(self):
        """Legacy is_error property works correctly."""
        success = ToolResult("success")
        failure = ToolResult("", "failed")
        
        assert success.is_error is False
        assert failure.is_error is True

    def test_legacy_str_conversion(self):
        """Legacy str() conversion works."""
        success = ToolResult("success")
        failure = ToolResult("", "failed")
        
        assert str(success) == "success"
        assert "ERROR" in str(failure)
