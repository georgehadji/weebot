"""Unit tests for Windows Desktop companion (Enhancement 4).

Covers:
- DesktopPort ABC verifies abstract methods
- DesktopStatus enum, DesktopPrompt/DesktopResponse dataclasses
- WindowsDesktopAdapter: dependency checks, status updates, lifecycle
- CLI companion command registration
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDesktopPortInterface:
    """Validates the DesktopPort ABC contract."""

    def test_abc_cannot_be_instantiated(self):
        """DesktopPort ABC cannot be instantiated directly."""
        from weebot.application.ports.desktop_port import DesktopPort

        with pytest.raises(TypeError, match="abstract"):
            DesktopPort()  # type: ignore[abstract]

    def test_concrete_adapter_inherits(self):
        """WindowsDesktopAdapter is a concrete DesktopPort."""
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
        )
        from weebot.application.ports.desktop_port import DesktopPort

        assert issubclass(WindowsDesktopAdapter, DesktopPort)


class TestDesktopDataTypes:
    """Validates DesktopStatus enum and data classes."""

    def test_status_values(self):
        from weebot.application.ports.desktop_port import DesktopStatus

        assert DesktopStatus.CONNECTED.value == "connected"
        assert DesktopStatus.CONNECTING.value == "connecting"
        assert DesktopStatus.DISCONNECTED.value == "disconnected"
        assert DesktopStatus.ERROR.value == "error"

    def test_desktop_prompt_defaults(self):
        from weebot.application.ports.desktop_port import DesktopPrompt

        p = DesktopPrompt(text="hello")
        assert p.text == "hello"
        assert p.session_id is None

    def test_desktop_response_defaults(self):
        from weebot.application.ports.desktop_port import DesktopResponse

        r = DesktopResponse(text="response text")
        assert r.text == "response text"
        assert r.success is True
        assert r.tool_calls == 0


class TestWindowsDesktopAdapter:
    """Validates WindowsDesktopAdapter core logic (GUI-agnostic parts)."""

    def test_initial_status_is_disconnected(self):
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
            DesktopStatus,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())
        assert adapter._status == DesktopStatus.DISCONNECTED

    def test_set_status_updates_internal(self):
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
            DesktopStatus,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())
        adapter.set_status(DesktopStatus.CONNECTED)
        assert adapter._status == DesktopStatus.CONNECTED

    def test_set_status_error(self):
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
            DesktopStatus,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())
        adapter.set_status(DesktopStatus.ERROR)
        assert adapter._status == DesktopStatus.ERROR

    def test_stop_sets_disconnected(self):
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
            DesktopStatus,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())

        async def _test():
            adapter._running = True
            await adapter.stop()
            assert adapter._status == DesktopStatus.DISCONNECTED
            assert adapter._running is False

        import asyncio
        asyncio.run(_test())

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
            DesktopStatus,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())

        # Mock pystray/keyboard imports to avoid GUI
        with patch.multiple(
            "weebot.infrastructure.adapters.windows_desktop",
            _PYSTRAY_AVAILABLE=False,
            _TKINTER_AVAILABLE=False,
            _KEYBOARD_AVAILABLE=False,
        ):
            await adapter.start()
            assert adapter._status == DesktopStatus.CONNECTED
            assert adapter._running is True

            await adapter.stop()
            assert adapter._status == DesktopStatus.DISCONNECTED
            assert adapter._running is False

    @pytest.mark.asyncio
    async def test_show_overlay_when_tkinter_unavailable(self):
        """When tkinter is not available, show_overlay returns None."""
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())

        with patch(
            "weebot.infrastructure.adapters.windows_desktop._TKINTER_AVAILABLE",
            False,
        ):
            result = await adapter.show_overlay()
            assert result is None

    @pytest.mark.asyncio
    async def test_start_stop_graceful_when_not_running(self):
        """Calling stop when not running is a no-op."""
        from weebot.infrastructure.adapters.windows_desktop import (
            WindowsDesktopAdapter,
        )

        adapter = WindowsDesktopAdapter(loop=AsyncMock())
        await adapter.stop()
        assert adapter._running is False


class TestCompanionCLI:
    """Validates the `weebot companion` command."""

    def test_companion_command_registered(self):
        """The companion command exists in the CLI group."""
        from cli.main import cli

        commands = [cmd.name for cmd in cli.commands.values()]
        assert "companion" in commands

    def test_companion_command_help(self):
        """Companion command has a descriptive help text."""
        from cli.main import companion

        assert "companion" in companion.help or "tray" in companion.help
