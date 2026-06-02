"""MCP client manager supporting stdio, SSE, and streamable-http transports."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

try:
    from mcp.client.streamable_http import streamablehttp_client
    HAS_STREAMABLE_HTTP = True
except ImportError:
    HAS_STREAMABLE_HTTP = False

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Manages connections to multiple MCP servers with retry and reconnection."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
    ):
        self._config = config or {}
        self._clients: Dict[str, ClientSession] = {}
        self._exit_stack = AsyncExitStack()
        self._tools_cache: Dict[str, List[Any]] = {}
        self._initialized = False
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._connection_attempts: Dict[str, int] = {}

    async def initialize(self) -> None:
        if self._initialized:
            return
        servers = self._config.get("mcpServers", {})
        failed: list[str] = []
        for server_name, server_config in servers.items():
            if not server_config.get("enabled", True):
                continue
            try:
                await self._connect_with_retry(server_name, server_config)
            except Exception as exc:
                logger.error("Failed to connect to MCP server %s: %s", server_name, exc)
                failed.append(server_name)
        self._initialized = True
        if failed and not self._clients:
            raise RuntimeError(
                f"All MCP servers failed to connect: {', '.join(failed)}"
            )

    async def _connect_with_retry(
        self,
        server_name: str,
        server_config: Dict[str, Any],
    ) -> None:
        """Connect to a server with exponential backoff retry.

        Raises:
            RuntimeError: If all retry attempts are exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                await self._connect_server(server_name, server_config)
                self._connection_attempts[server_name] = attempt
                logger.info("Connected to MCP server %s on attempt %d", server_name, attempt)
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Failed to connect to MCP server %s (attempt %d/%d): %s",
                    server_name, attempt, self._max_retries, exc
                )
                if attempt < self._max_retries:
                    delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
                    await asyncio.sleep(delay)
        logger.error("Permanent failure connecting to MCP server %s", server_name)
        raise RuntimeError(
            f"MCP server {server_name!r} failed after {self._max_retries} attempts"
        ) from last_exc

    async def _connect_server(self, server_name: str, server_config: Dict[str, Any]) -> None:
        transport = server_config.get("transport", "stdio")
        valid_transports = {"stdio", "http", "sse", "streamable-http"}
        if transport not in valid_transports:
            raise ValueError(
                f"Server {server_name} has invalid transport {transport!r}. "
                f"Valid transports: {valid_transports}"
            )
        if transport == "stdio":
            await self._connect_stdio(server_name, server_config)
        elif transport in ("http", "sse"):
            await self._connect_sse(server_name, server_config)
        elif transport == "streamable-http":
            await self._connect_streamable_http(server_name, server_config)

    async def _connect_stdio(self, server_name: str, config: Dict[str, Any]) -> None:
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env", {})
        if not command:
            raise ValueError(f"Server {server_name} missing command")
        params = StdioServerParameters(
            command=command,
            args=args,
            env={**os.environ, **env},
        )
        transport = await self._exit_stack.enter_async_context(stdio_client(params))
        read_stream, write_stream = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._clients[server_name] = session
        await self._cache_tools(server_name, session)

    async def _connect_sse(self, server_name: str, config: Dict[str, Any]) -> None:
        url = config.get("url")
        if not url:
            raise ValueError(f"Server {server_name} missing url")
        transport = await self._exit_stack.enter_async_context(sse_client(url))
        read_stream, write_stream = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._clients[server_name] = session
        await self._cache_tools(server_name, session)

    async def _connect_streamable_http(self, server_name: str, config: Dict[str, Any]) -> None:
        if not HAS_STREAMABLE_HTTP:
            raise RuntimeError("streamable-http client not available in this MCP version")
        url = config.get("url")
        if not url:
            raise ValueError(f"Server {server_name} missing url")
        headers = config.get("headers", {})
        params: Dict[str, Any] = {"url": url}
        if headers:
            params["headers"] = headers
        transport = await self._exit_stack.enter_async_context(streamablehttp_client(**params))
        if len(transport) == 3:
            read_stream, write_stream, _ = transport
        else:
            read_stream, write_stream = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._clients[server_name] = session
        await self._cache_tools(server_name, session)

    async def _cache_tools(self, server_name: str, session: ClientSession) -> None:
        try:
            tools_response = await session.list_tools()
            tools = tools_response.tools if tools_response else []
            self._tools_cache[server_name] = tools
        except Exception as exc:
            logger.warning("Failed to cache tools for %s: %s", server_name, exc)
            self._tools_cache[server_name] = []

    async def reconnect(self, server_name: str) -> bool:
        """Explicitly reconnect a single server."""
        servers = self._config.get("mcpServers", {})
        server_config = servers.get(server_name)
        if not server_config:
            logger.error("Cannot reconnect unknown server %s", server_name)
            return False
        self._clients.pop(server_name, None)
        self._tools_cache.pop(server_name, None)
        try:
            await self._connect_with_retry(server_name, server_config)
            return True
        except Exception as exc:
            logger.error("Reconnection failed for %s: %s", server_name, exc)
            return False

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """Return all MCP tools as OpenAI function specs."""
        all_tools: List[Dict[str, Any]] = []
        for server_name, tools in self._tools_cache.items():
            prefix = server_name if server_name.startswith("mcp_") else f"mcp_{server_name}"
            for tool in tools:
                tool_name = f"{prefix}_{tool.name}"
                all_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"[{server_name}] {tool.description or tool.name}",
                        "parameters": tool.inputSchema,
                    },
                })
        return all_tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call an MCP tool by its prefixed name with health check."""
        server_name = None
        original_name = None
        servers = self._config.get("mcpServers", {})
        for srv_name in servers.keys():
            expected_prefix = srv_name if srv_name.startswith("mcp_") else f"mcp_{srv_name}"
            if tool_name.startswith(f"{expected_prefix}_"):
                server_name = srv_name
                original_name = tool_name[len(expected_prefix) + 1:]
                break
        if not server_name or not original_name:
            raise ValueError(f"Cannot parse MCP tool name: {tool_name}")

        session = self._clients.get(server_name)
        if not session:
            logger.warning("MCP server %s not connected; attempting reconnect", server_name)
            ok = await self.reconnect(server_name)
            if not ok:
                raise RuntimeError(f"MCP server {server_name} not connected and reconnection failed")
            session = self._clients.get(server_name)
            if not session:
                raise RuntimeError(f"MCP server {server_name} still not connected after reconnect")

        try:
            result = await session.call_tool(original_name, arguments)
        except Exception as exc:
            logger.warning("MCP tool call failed for %s:%s: %s", server_name, original_name, exc)
            raise RuntimeError(f"MCP tool call failed: {exc}") from exc

        content: List[str] = []
        if hasattr(result, "content") and result.content:
            for item in result.content:
                if hasattr(item, "text"):
                    content.append(item.text)
                else:
                    content.append(str(item))
        return "\n".join(content) if content else "OK"

    async def cleanup(self) -> None:
        await self._exit_stack.aclose()
        self._clients.clear()
        self._tools_cache.clear()
        self._initialized = False
        self._connection_attempts.clear()
