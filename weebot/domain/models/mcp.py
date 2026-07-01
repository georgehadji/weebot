"""MCP domain models — server config, tool info, connection state.

These models describe the MCP (Model Context Protocol) server topology
that Weebot connects to.  They are pure domain models with no dependency
on the MCP SDK or any infrastructure adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class MCPTransport(str, Enum):
    """Supported MCP transport protocols."""
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class MCPConnectionState(str, Enum):
    """Lifecycle state of a connection to an MCP server."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class MCPAuthConfig(BaseModel):
    """Authentication configuration for an MCP server.

    Supports OAuth (for hosted MCP servers like Stripe) and
    bearer token / mTLS for private servers.
    """
    type: str = Field(default="none", description="Auth type: none, oauth, bearer, mtls")
    oauth_client_id: str | None = Field(default=None, description="OAuth client ID")
    oauth_scopes: list[str] = Field(default_factory=list, description="OAuth scopes")
    token: str | None = Field(default=None, description="Bearer token or API key")
    client_cert_path: str | None = Field(default=None, description="mTLS client cert path")
    client_key_path: str | None = Field(default=None, description="mTLS client key path")


class MCPToolFilterConfig(BaseModel):
    """Filtering rules for tools exposed by an MCP server."""
    include: list[str] | None = Field(default=None, description="Glob patterns to include")
    exclude: list[str] | None = Field(default=None, description="Glob patterns to exclude")
    include_prompts: bool = Field(default=False, description="Expose prompts as tools")
    include_resources: bool = Field(default=False, description="Expose resources as tools")
    write_tools: list[str] | None = Field(
        default=None,
        description=(
            "Glob patterns for write/destructive tools that should be "
            "admin-only + restricted tier.  If None, all tools are gated "
            "equally (legacy behaviour)."
        ),
    )


class MCPSamplingPolicy(BaseModel):
    """Policy for handling sampling/createMessage requests from an MCP server."""
    enabled: bool = Field(default=True, description="Allow sampling requests")
    max_tokens_per_request: int = Field(default=4096, ge=1, le=65536)
    model_allowlist: list[str] | None = Field(
        default=None,
        description="Allowed model IDs for sampling. None = allow all configured models.",
    )
    rate_limit_per_minute: int = Field(default=10, ge=0, description="0 = unlimited")


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server connection.

    Supports stdio subprocess (command + args + env), HTTP/SSE streaming
    connections (url + headers), and streamable-http.
    """
    name: str = Field(description="Unique server identifier")
    transport: MCPTransport = Field(default=MCPTransport.STDIO)
    enabled: bool = Field(default=True, description="Connect on startup")

    # Stdio transport
    command: str | None = Field(default=None, description="Executable path (stdio transport)")
    args: list[str] = Field(default_factory=list, description="CLI arguments (stdio transport)")
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Extra env vars for the subprocess. Overlaid on safe baseline.",
    )

    # HTTP/SSE transport
    url: str | None = Field(default=None, description="Server URL (http/sse/streamable-http)")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")

    # Auth
    auth: MCPAuthConfig = Field(default_factory=MCPAuthConfig)

    # Tool filtering
    tools: MCPToolFilterConfig = Field(default_factory=MCPToolFilterConfig)

    # Sampling policy
    sampling: MCPSamplingPolicy = Field(default_factory=MCPSamplingPolicy)

    # Timeouts
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    parallel_calls: bool = Field(default=True, description="Allow concurrent tool calls")
    max_parallel: int = Field(default=5, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("MCP server name must not be empty")
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"MCP server name must be alphanumeric (dashes/underscores allowed): {v!r}"
            )
        return v.strip()

    @model_validator(mode="after")
    def _validate_transport_requirements(self) -> "MCPServerConfig":
        """Validate transport-specific required fields."""
        if self.transport == MCPTransport.STDIO and not self.command:
            raise ValueError("command is required for stdio transport")
        if self.transport in (MCPTransport.HTTP, MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP) and not self.url:
            raise ValueError(f"url is required for {self.transport} transport")
        return self


class MCPToolInfo(BaseModel):
    """Information about a tool exposed by an MCP server.

    Stored per-server after tool discovery, before filtering is applied.
    """
    original_name: str = Field(description="Tool name as returned by the MCP server")
    namespaced_name: str = Field(description="Namespaced name: mcp__<server>__<tool>")
    description: str = Field(default="", description="Tool description from the server")
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for tool parameters",
    )
    server_name: str = Field(description="Originating server name")


class MCPConnectionMetrics(BaseModel):
    """Runtime metrics for a single MCP server connection."""
    server_name: str
    state: MCPConnectionState = MCPConnectionState.DISCONNECTED
    connected_at: datetime | None = None
    last_health_check: datetime | None = None
    tool_count: int = 0
    call_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    last_error_at: datetime | None = None
    avg_latency_ms: float = 0.0
    uptime_seconds: float = 0.0

    def update_uptime(self) -> None:
        if self.connected_at and self.state == MCPConnectionState.CONNECTED:
            self.uptime_seconds = (
                datetime.now(timezone.utc) - self.connected_at
            ).total_seconds()
        else:
            self.uptime_seconds = 0.0
