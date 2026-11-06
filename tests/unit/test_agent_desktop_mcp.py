"""agent-desktop is wired in as an untrusted stdio MCP server, and desktop steps are sent its tools."""

from __future__ import annotations

import json
from pathlib import Path

from weebot.application.services.tool_scope import select_tools
from weebot.core.mcp_naming import build_namespaced_name

CONFIG = Path(__file__).resolve().parents[2] / "config" / "mcp_servers.json"
TOOL = build_namespaced_name("agent_desktop", "desktop_snapshot")


def test_the_server_is_configured_to_run_the_installed_cli_over_stdio():
    entry = json.loads(CONFIG.read_text(encoding="utf-8"))["agent_desktop"]

    assert (entry["transport"], entry["command"], entry["args"]) == ("stdio", "agent-desktop", ["mcp"])


def test_the_server_is_not_marked_trusted_so_every_desktop_action_asks():
    entry = json.loads(CONFIG.read_text(encoding="utf-8"))["agent_desktop"]

    assert entry.get("trust", "untrusted") == "untrusted"


def test_the_tools_carry_the_namespaced_name_the_scope_looks_for():
    assert TOOL == "mcp__agent_desktop__desktop_snapshot"


def test_a_desktop_step_is_sent_the_agent_desktop_tools_and_a_weather_step_is_not():
    available = {TOOL, "web_search"}

    assert TOOL in select_tools("Open the desktop app and click Save", available)
    assert TOOL not in select_tools("What is the weather in Athens", available)
