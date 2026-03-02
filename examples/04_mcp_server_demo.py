"""Example 04 — MCP Server Demo
=================================
Shows WeebotMCPServer capabilities without starting a live network server.

  Part A  Introspect registered tools and resources
  Part B  Invoke two tools via server.mcp.call_tool()  (mocked subprocess)
  Part C  Read all three resources via server.mcp.read_resource()
  Part D  Print live / real transport instructions for Claude Desktop & IDE

In production you would start the server with:
    await server.run_stdio()   — stdin/stdout for Claude Desktop
    await server.run_sse()     — HTTP/SSE  for Claude IDE

Usage:
    python examples/04_mcp_server_demo.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from weebot.activity_stream import ActivityStream
from weebot.mcp.server import WeebotMCPServer
from weebot.tools.base import ToolResult


async def part_a_introspect(server: WeebotMCPServer) -> None:
    """List all registered tools and resources."""
    print("━" * 56)
    print(" Part A — Registered tools & resources")
    print("━" * 56)

    tools = await server.mcp.list_tools()
    print(f"\n🛠️   Tools ({len(tools)}):")
    for tool in tools:
        desc_short = (tool.description or "")[:65].rstrip()
        print(f"  • {tool.name:<20} {desc_short}…")

    resources = await server.mcp.list_resources()
    print(f"\n📦  Resources ({len(resources)}):")
    for res in resources:
        print(f"  • {str(res.uri):<28} [{res.mimeType}]")

    print()


async def part_b_tool_calls(server: WeebotMCPServer) -> None:
    """Invoke tools through the MCP layer (subprocess mocked for offline demo)."""
    print("━" * 56)
    print(" Part B — Tool calls via MCP (mocked subprocess)")
    print("━" * 56)

    # ── bash tool ────────────────────────────────────────────────────────
    bash_output = "Hello from PowerShell\n"
    with patch(
        "weebot.tools.bash_tool.BashTool.execute",
        new=AsyncMock(return_value=ToolResult(output=bash_output)),
    ):
        content, _ = await server.mcp.call_tool(
            "bash", {"command": "Write-Output 'Hello from PowerShell'"}
        )
    print(f"\n🖥️   bash result:           {content[0].text!r}")

    # ── python_execute tool ───────────────────────────────────────────────
    py_output = "The answer is 42\n"
    with patch(
        "weebot.tools.python_tool.PythonExecuteTool.execute",
        new=AsyncMock(return_value=ToolResult(output=py_output)),
    ):
        content, _ = await server.mcp.call_tool(
            "python_execute", {"code": "print('The answer is', 6 * 7)"}
        )
    print(f"🐍   python_execute result: {content[0].text!r}")

    # ── web_search tool ───────────────────────────────────────────────────
    ws_output = "1. MCP Protocol Docs — https://modelcontextprotocol.io\n"
    with patch(
        "weebot.tools.web_search.WebSearchTool.execute",
        new=AsyncMock(return_value=ToolResult(output=ws_output)),
    ):
        content, _ = await server.mcp.call_tool(
            "web_search", {"query": "Model Context Protocol"}
        )
    print(f"🔍   web_search result:     {content[0].text!r}")
    print()


async def part_c_resources(server: WeebotMCPServer, stream: ActivityStream) -> None:
    """Read all three resource URIs."""
    print("━" * 56)
    print(" Part C — Resource reads")
    print("━" * 56)

    uris = ["weebot://activity", "weebot://state", "weebot://schedule"]
    for uri in uris:
        contents = await server.mcp.read_resource(uri)
        raw = contents[0].content
        data = json.loads(raw)
        print(f"\n📋  {uri}")
        if uri == "weebot://activity":
            print(f"    events: {len(data)}")
            for e in data[:3]:
                print(f"    [{e['kind']}] {e['message']}")
        else:
            print(f"    {json.dumps(data, indent=4)[:200]}")
    print()


def part_d_transport_guide() -> None:
    """Print production transport instructions."""
    print("━" * 56)
    print(" Part D — Production transport options")
    print("━" * 56)
    print("""
  ┌─ Claude Desktop (stdio) ─────────────────────────┐
  │                                                   │
  │  server = WeebotMCPServer()                       │
  │  asyncio.run(server.run_stdio())                  │
  │                                                   │
  │  claude_desktop_config.json entry:                │
  │  {                                                │
  │    "mcpServers": {                                │
  │      "weebot": {                                  │
  │        "command": "python",                       │
  │        "args": ["run.py", "--mcp-stdio"]          │
  │      }                                            │
  │    }                                              │
  │  }                                                │
  └───────────────────────────────────────────────────┘

  ┌─ Claude IDE / Web (SSE on localhost:8765) ────────┐
  │                                                   │
  │  server = WeebotMCPServer(port=8765)              │
  │  asyncio.run(server.run_sse())                    │
  │                                                   │
  │  MCP endpoint: http://127.0.0.1:8765/sse          │
  └───────────────────────────────────────────────────┘
""")


async def main() -> None:
    stream = ActivityStream()
    # Seed the activity stream so Part C shows real events
    stream.push("demo", "startup", "WeebotMCPServer demo initialised")
    stream.push("demo", "tool", "bash: Write-Output (mocked)")
    stream.push("demo", "tool", "python_execute: print(6*7) (mocked)")

    server = WeebotMCPServer(activity_stream=stream, host="127.0.0.1", port=8765)

    print("\n🚀  weebot — MCP Server Demo")
    print(f"    Server name : {server.mcp.name!r}\n")

    await part_a_introspect(server)
    await part_b_tool_calls(server)
    await part_c_resources(server, stream)
    part_d_transport_guide()

    print("✅  Demo complete.\n")


if __name__ == "__main__":
    asyncio.run(main())
