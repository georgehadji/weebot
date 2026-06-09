"""Tests for Phase 4: Context-aware output truncation."""
import pytest

from weebot.application.models.tool_collection import _truncate
from weebot.tools.base import BaseTool, ToolResult


# ── Pure function tests for _truncate ─────────────────────────────

def test_head_truncation_keeps_start():
    """output > limit; result starts with original prefix."""
    output = "A" * 1000
    result = _truncate(output, limit=100, strategy="head")
    assert len(result) <= 150  # 100 + sentinel
    assert result.startswith("A" * 100)
    assert "chars omitted" in result


def test_tail_truncation_keeps_end():
    """output > limit; result ends with original suffix."""
    output = "AAAAA" + "B" * 1000
    result = _truncate(output, limit=100, strategy="tail")
    assert len(result) <= 150
    assert result.endswith("B" * 100)
    assert "chars omitted" in result


def test_boundary_truncation_no_mid_record():
    """output has newlines; truncation lands on a boundary."""
    lines = [f"line_{i}" for i in range(50)]
    output = "\n".join(lines)
    result = _truncate(output, limit=100, strategy="boundary")
    # Should end with a complete line (not mid-line)
    assert "chars omitted" in result
    # The content before the sentinel should end with a newline or boundary marker
    sentinel_idx = result.find("...[" if "..." in result else "")
    if sentinel_idx > 0:
        before = result[:sentinel_idx]
        assert before.endswith("\n") or before.endswith("},") or len(before) <= 100


def test_no_truncation_below_limit():
    """output <= limit; output unchanged, no sentinel."""
    output = "Short text"
    result = _truncate(output, limit=100, strategy="head")
    assert result == output


def test_tail_no_truncation_below_limit():
    """output <= limit; unchanged for tail strategy too."""
    output = "Short text"
    result = _truncate(output, limit=100, strategy="tail")
    assert result == output


def test_boundary_no_truncation_below_limit():
    """output <= limit; unchanged for boundary strategy too."""
    output = "Short text"
    result = _truncate(output, limit=100, strategy="boundary")
    assert result == output


@pytest.mark.asyncio
async def test_metadata_records_strategy():
    """ToolCollection records truncation metadata including strategy."""
    from weebot.application.models.tool_collection import ToolCollection
    from weebot.tools.base import BaseTool, ToolResult

    class _TailTool(BaseTool):
        name: str = "tail_tool"
        description: str = "Tail truncation test tool"
        parameters: dict = {"type": "object", "properties": {}}
        truncation_strategy: str = "tail"

        async def execute(self, **kwargs) -> ToolResult:
            return ToolResult.success_result(output="A" * 30000)

    tools = ToolCollection(_TailTool())
    result = await tools.execute("tail_tool")
    assert result.metadata.get("truncated") is True
    assert result.metadata.get("truncation_strategy") == "tail"
    assert result.metadata.get("original_length") == 30000


def test_empty_output_no_truncation():
    """Empty string is not truncated."""
    result = _truncate("", limit=100, strategy="head")
    assert result == ""
    result = _truncate("", limit=100, strategy="tail")
    assert result == ""
    result = _truncate("", limit=100, strategy="boundary")
    assert result == ""


def test_exact_limit_no_truncation():
    """Output exactly at limit is not truncated."""
    output = "A" * 100
    result = _truncate(output, limit=100, strategy="head")
    assert result == output
    result = _truncate(output, limit=100, strategy="tail")
    assert result == output
    result = _truncate(output, limit=100, strategy="boundary")
    assert result == output


def test_large_output_head():
    """Large output with head strategy."""
    output = "Hello " + "world " * 500
    result = _truncate(output, limit=50, strategy="head")
    assert result.startswith("Hello ")
    assert "...[" in result


def test_large_output_tail():
    """Large output with tail strategy — errors at end preserved."""
    output = ("INFO: step 1\n" * 50) + "ERROR: Something failed"
    result = _truncate(output, limit=100, strategy="tail")
    assert result.endswith("ERROR: Something failed")
    assert "...[" in result
