"""One rule for turning a sandbox run into a tool result (audit R12)."""

from __future__ import annotations

from weebot.application.ports.sandbox_port import SandboxResult
from weebot.tools.base import ToolResult


def to_tool_result(result: SandboxResult, *, timeout: float, label: str = "Command") -> ToolResult:
    """A non-zero exit is an error even when stderr is empty; stderr on exit 0 is output."""
    if result.timed_out:
        return ToolResult(output="", error=f"{label} timed out after {timeout:.0f}s")
    if result.memory_killed:
        return ToolResult(output=result.stdout, error=f"{label} killed: memory limit exceeded")
    if not result.success:
        return ToolResult(
            output=result.stdout, error=result.stderr or f"Exit code {result.returncode}"
        )
    return ToolResult(output=result.combined_output)
