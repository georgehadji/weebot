"""Unit tests for PowerShellTool and ScreenCaptureBaseTool wrappers."""
import pytest
from unittest.mock import patch

from weebot.tools.powershell_tool import PowerShellTool
from weebot.tools.screen_tool import ScreenCaptureBaseTool


# ---------------------------------------------------------------------------
# PowerShellTool
# ---------------------------------------------------------------------------


class TestPowerShellTool:
    def test_instantiates_without_error(self):
        tool = PowerShellTool()
        assert tool.name == "powershell"

    def test_to_param_shape(self):
        tool = PowerShellTool()
        param = tool.to_param()
        assert param["type"] == "function"
        assert param["function"]["name"] == "powershell"
        assert "command" in param["function"]["parameters"]["required"]

    @pytest.mark.asyncio
    async def test_execute_returns_output(self):
        tool = PowerShellTool()
        with patch.object(tool._sandbox, "execute_shell") as mock:
            from weebot.application.ports.sandbox_port import SandboxResult, SandboxType
            mock.return_value = SandboxResult(
                stdout="Hello", stderr="", returncode=0,
                elapsed_ms=1.0, sandbox_type=SandboxType.NATIVE_WINDOWS,
            )
            result = await tool.execute(command="echo Hello")
        assert not result.is_error
        assert "Hello" in result.output

    @pytest.mark.asyncio
    async def test_execute_error_returns_error(self):
        tool = PowerShellTool()
        with patch.object(tool._sandbox, "execute_shell") as mock:
            from weebot.application.ports.sandbox_port import SandboxResult, SandboxType
            mock.return_value = SandboxResult(
                stdout="", stderr="sandbox violation", returncode=1,
                elapsed_ms=1.0, sandbox_type=SandboxType.NATIVE_WINDOWS,
            )
            result = await tool.execute(command="bad command")
        assert result.is_error
        assert "sandbox violation" in result.error

    @pytest.mark.asyncio
    async def test_execute_exception_becomes_tool_error(self):
        tool = PowerShellTool()
        with patch.object(tool._sandbox, "execute_shell", side_effect=RuntimeError("crash")):
            result = await tool.execute(command="crash")
        assert result.is_error
        assert "crash" in result.error


# ---------------------------------------------------------------------------
# ScreenCaptureBaseTool
# ---------------------------------------------------------------------------


class TestScreenCaptureBaseTool:
    def test_instantiates_without_error(self):
        tool = ScreenCaptureBaseTool()
        assert tool.name == "screen_capture"

    def test_to_param_shape(self):
        tool = ScreenCaptureBaseTool()
        param = tool.to_param()
        assert param["type"] == "function"
        assert param["function"]["name"] == "screen_capture"

    @pytest.mark.asyncio
    async def test_execute_success_returns_base64(self):
        tool = ScreenCaptureBaseTool()
        fake_png = b"\x89PNG\r\n\x1a\n"
        with patch.object(
            tool._inner,
            "capture",
            return_value={
                "success": True,
                "output": "Captured monitor 0 (1920x1080)",
                "data": fake_png,
            },
        ):
            result = await tool.execute(monitor_index=0)
        assert not result.is_error
        assert result.base64_image is not None
        # Verify it's valid base64 by decoding it back
        import base64
        decoded = base64.b64decode(result.base64_image)
        assert decoded == fake_png

    @pytest.mark.asyncio
    async def test_execute_failure_is_tool_error(self):
        tool = ScreenCaptureBaseTool()
        with patch.object(
            tool._inner,
            "capture",
            return_value={"success": False, "output": "mss not installed", "data": None},
        ):
            result = await tool.execute(monitor_index=0)
        assert result.is_error
        assert "mss not installed" in result.error

    @pytest.mark.asyncio
    async def test_execute_invalid_monitor_is_error(self):
        tool = ScreenCaptureBaseTool()
        with patch.object(
            tool._inner,
            "capture",
            return_value={"success": False, "output": "Invalid monitor index 5", "data": None},
        ):
            result = await tool.execute(monitor_index=5)
        assert result.is_error
