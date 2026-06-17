"""Unit tests for MCP domain models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from weebot.domain.models.mcp import (
    MCPServerConfig,
    MCPToolInfo,
    MCPConnectionState,
    MCPTransport,
    MCPAuthConfig,
    MCPToolFilterConfig,
    MCPSamplingPolicy,
    MCPConnectionMetrics,
)


class TestMCPServerConfig:
    """MCPServerConfig validation and defaults."""

    def test_minimal_stdio_config(self):
        """A stdio server needs at minimum a name and command."""
        config = MCPServerConfig(name="test-server", command="npx")
        assert config.name == "test-server"
        assert config.transport == MCPTransport.STDIO
        assert config.command == "npx"
        assert config.enabled is True
        assert config.timeout_seconds == 30

    def test_stdio_without_command_raises(self):
        """MCPServerConfig raises if stdio transport has no command."""
        with pytest.raises(ValidationError):
            MCPServerConfig(name="bad-server", transport="stdio")

    def test_http_server_requires_url(self):
        """HTTP/SSE servers require a url."""
        with pytest.raises(ValidationError):
            MCPServerConfig(name="http-server", transport="sse")

    def test_http_with_url_ok(self):
        """HTTP server with url is valid."""
        config = MCPServerConfig(name="my-api", transport="sse", url="http://localhost:8080/mcp")
        assert config.url == "http://localhost:8080/mcp"

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(name="", command="npx")

    def test_invalid_name_raises(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(name="bad name!", command="npx")

    def test_name_with_dashes_ok(self):
        config = MCPServerConfig(name="my-server", command="python")
        assert config.name == "my-server"

    def test_name_with_underscores_ok(self):
        config = MCPServerConfig(name="my_server", command="python")
        assert config.name == "my_server"

    def test_full_stdio_config(self):
        config = MCPServerConfig(
            name="full-server",
            command="python",
            args=["-m", "mcp_server"],
            env={"DEBUG": "1"},
            timeout_seconds=60,
            parallel_calls=False,
            max_parallel=2,
        )
        assert config.command == "python"
        assert config.args == ["-m", "mcp_server"]
        assert config.env == {"DEBUG": "1"}
        assert config.timeout_seconds == 60
        assert config.parallel_calls is False
        assert config.max_parallel == 2

    def test_auth_config_defaults(self):
        config = MCPServerConfig(name="auth-server", command="npx")
        assert config.auth.type == "none"
        assert config.auth.oauth_scopes == []

    def test_tool_filter_defaults(self):
        config = MCPServerConfig(name="filter-server", command="npx")
        assert config.tools.include is None
        assert config.tools.exclude is None
        assert config.tools.include_prompts is False

    def test_sampling_policy_defaults(self):
        config = MCPServerConfig(name="sample-server", command="npx")
        assert config.sampling.enabled is True
        assert config.sampling.max_tokens_per_request == 4096
        assert config.sampling.rate_limit_per_minute == 10


class TestMCPToolInfo:
    """MCPToolInfo creation and attributes."""

    def test_minimal_tool_info(self):
        info = MCPToolInfo(
            original_name="get_weather",
            namespaced_name="mcp__weather__get_weather",
            server_name="weather",
        )
        assert info.original_name == "get_weather"
        assert info.namespaced_name == "mcp__weather__get_weather"
        assert info.server_name == "weather"
        assert info.description == ""
        assert info.input_schema == {"type": "object", "properties": {}}

    def test_full_tool_info(self):
        info = MCPToolInfo(
            original_name="create_payment",
            namespaced_name="mcp__stripe__create_payment",
            description="Create a payment intent",
            input_schema={
                "type": "object",
                "properties": {
                    "amount": {"type": "integer"},
                    "currency": {"type": "string"},
                },
                "required": ["amount"],
            },
            server_name="stripe",
        )
        assert info.description == "Create a payment intent"
        assert info.input_schema["required"] == ["amount"]


class TestMCPConnectionMetrics:
    """MCPConnectionMetrics uptime tracking."""

    def test_default_metrics(self):
        metrics = MCPConnectionMetrics(server_name="test")
        assert metrics.server_name == "test"
        assert metrics.state == MCPConnectionState.DISCONNECTED
        assert metrics.tool_count == 0
        assert metrics.call_count == 0
        assert metrics.error_count == 0
        assert metrics.uptime_seconds == 0.0

    def test_uptime_when_disconnected(self):
        metrics = MCPConnectionMetrics(server_name="test")
        metrics.update_uptime()
        assert metrics.uptime_seconds == 0.0

    def test_state_values(self):
        assert MCPConnectionState.DISCONNECTED.value == "disconnected"
        assert MCPConnectionState.CONNECTING.value == "connecting"
        assert MCPConnectionState.CONNECTED.value == "connected"
        assert MCPConnectionState.ERROR.value == "error"


class TestMCPAuthConfig:
    """MCPAuthConfig validation."""

    def test_defaults(self):
        auth = MCPAuthConfig()
        assert auth.type == "none"
        assert auth.token is None

    def test_oauth_config(self):
        auth = MCPAuthConfig(
            type="oauth",
            oauth_client_id="client_123",
            oauth_scopes=["read", "write"],
        )
        assert auth.type == "oauth"
        assert auth.oauth_client_id == "client_123"
        assert auth.oauth_scopes == ["read", "write"]


class TestMCPToolFilterConfig:
    """MCPToolFilterConfig include/exclude logic."""

    def test_include_only(self):
        filt = MCPToolFilterConfig(include=["get_*", "list_*"])
        assert filt.include == ["get_*", "list_*"]
        assert filt.exclude is None

    def test_exclude_only(self):
        filt = MCPToolFilterConfig(exclude=["delete_*", "admin_*"])
        assert filt.exclude == ["delete_*", "admin_*"]

    def test_include_resources(self):
        filt = MCPToolFilterConfig(include_resources=True)
        assert filt.include_resources is True


class TestMCPSamplingPolicy:
    """MCPSamplingPolicy configuration."""

    def test_defaults(self):
        policy = MCPSamplingPolicy()
        assert policy.enabled is True
        assert policy.max_tokens_per_request == 4096
        assert policy.rate_limit_per_minute == 10

    def test_model_allowlist(self):
        policy = MCPSamplingPolicy(model_allowlist=["claude-3-sonnet", "gpt-4"])
        assert policy.model_allowlist == ["claude-3-sonnet", "gpt-4"]

    def test_disabled(self):
        policy = MCPSamplingPolicy(enabled=False)
        assert policy.enabled is False
