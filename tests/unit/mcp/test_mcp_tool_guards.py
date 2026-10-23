"""F09 wiring: the MCP server's bash and python_execute go through the guard chain.

The MCP server calls these tools directly, outside ToolExecutor and its egress
check, so W3.2 wraps them where they are built (weebot/mcp/server.py).
"""

from weebot.application.services import tool_guards
from weebot.application.services.tool_guards import GuardedTool
from weebot.mcp.server import WeebotMCPServer


def test_server_wraps_its_code_running_tools(monkeypatch):
    seen: list[list] = []
    real = tool_guards.guard_tools

    def _spy(tools, **kwargs):
        wrapped = real(tools, **kwargs)
        seen.append(wrapped)
        return wrapped

    monkeypatch.setattr(tool_guards, "guard_tools", _spy)
    WeebotMCPServer()

    # The dynamic-tool registration also calls guard_tools (F06), here with none.
    seen = [s for s in seen if s]
    assert len(seen) == 1
    assert [t.name for t in seen[0]] == ["bash", "python_execute"]
    assert all(isinstance(t, GuardedTool) for t in seen[0])
