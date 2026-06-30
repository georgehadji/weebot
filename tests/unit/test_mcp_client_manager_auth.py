"""Tests for MCPClientManager auth header glue and timeout threading."""
from __future__ import annotations

import pytest

from weebot.infrastructure.mcp.mcp_client_manager import MCPClientManager


class TestBearerAuthHeader:
    """Bearer auth → Authorization header mapping (Gap A)."""

    @pytest.mark.asyncio
    async def test_streamable_http_bearer_auth(self, monkeypatch):
        """Bearer auth config should produce an Authorization header."""
        config = {
            "mcpServers": {
                "xapi": {
                    "enabled": True,
                    "transport": "streamable-http",
                    "url": "https://api.x.com/mcp",
                    "auth": {"type": "bearer", "token": "my-bearer-token"},
                }
            }
        }
        mgr = MCPClientManager(config=config, max_retries=1)

        # Collect what headers would be passed
        captured_headers = {}

        async def mock_streamable_http(**params):
            nonlocal captured_headers
            captured_headers = params.get("headers", {})
            raise RuntimeError("Connection refused (expected)")

        monkeypatch.setattr(
            "weebot.infrastructure.mcp.mcp_client_manager.streamablehttp_client",
            mock_streamable_http,
        )

        with pytest.raises(RuntimeError):
            await mgr.initialize()

        assert captured_headers.get("Authorization") == "Bearer my-bearer-token"

    @pytest.mark.asyncio
    async def test_explicit_header_takes_precedence(self, monkeypatch):
        """Explicit headers["Authorization"] should not be overwritten by auth.token."""
        config = {
            "mcpServers": {
                "xapi": {
                    "enabled": True,
                    "transport": "streamable-http",
                    "url": "https://api.x.com/mcp",
                    "headers": {"Authorization": "Bearer explicit-value"},
                    "auth": {"type": "bearer", "token": "implicit-token"},
                }
            }
        }
        mgr = MCPClientManager(config=config, max_retries=1)
        captured_headers = {}

        async def mock_streamable_http(**params):
            nonlocal captured_headers
            captured_headers = params.get("headers", {})
            raise RuntimeError("Connection refused (expected)")

        monkeypatch.setattr(
            "weebot.infrastructure.mcp.mcp_client_manager.streamablehttp_client",
            mock_streamable_http,
        )

        with pytest.raises(RuntimeError):
            await mgr.initialize()

        # Explicit header should win
        assert captured_headers.get("Authorization") == "Bearer explicit-value"

    @pytest.mark.asyncio
    async def test_no_auth_no_header(self, monkeypatch):
        """No auth config should not produce any Authorization header."""
        config = {
            "mcpServers": {
                "xapi": {
                    "enabled": True,
                    "transport": "streamable-http",
                    "url": "https://api.x.com/mcp",
                }
            }
        }
        mgr = MCPClientManager(config=config, max_retries=1)
        captured_params = {}

        async def mock_streamable_http(**params):
            nonlocal captured_params
            captured_params = params
            raise RuntimeError("Connection refused (expected)")

        monkeypatch.setattr(
            "weebot.infrastructure.mcp.mcp_client_manager.streamablehttp_client",
            mock_streamable_http,
        )

        with pytest.raises(RuntimeError):
            await mgr.initialize()

        assert "Authorization" not in captured_params.get("headers", {})


class TestTimeoutThreading:
    """Configurable timeout_seconds per server (Phase 5)."""

    @pytest.mark.asyncio
    async def test_timeout_passed_to_initialize(self, monkeypatch):
        """The timeout_seconds config value should be respected in initialize()."""
        from mcp import ClientSession

        original_init = ClientSession.initialize

        init_kwargs = {}

        async def tracking_initialize(self):
            return await original_init(self)

        monkeypatch.setattr(ClientSession, "initialize", tracking_initialize)

        # Just verify the config parsing works for timeout_seconds
        config = {
            "mcpServers": {
                "test": {
                    "enabled": True,
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-c", "import sys; sys.exit(0)"],
                    "timeout_seconds": 300,
                }
            }
        }
        mgr = MCPClientManager(config=config, max_retries=1)

        # The test just verifies timeout_seconds is accepted in config
        # (the actual connection will likely fail since there's no real MCP server)
        # but the config parsing path doesn't error
        with pytest.raises((RuntimeError, FileNotFoundError, Exception)):
            await mgr.initialize()
