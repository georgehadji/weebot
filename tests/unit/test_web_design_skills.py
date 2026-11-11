"""Website work is sent through the senior-frontend skill and the Awwwards MCP server."""

from __future__ import annotations

import json
from pathlib import Path

from weebot.application.services.tool_scope import select_tools
from weebot.application.skills.skill_registry import SkillRegistry
from weebot.core.mcp_naming import build_namespaced_name

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "mcp_servers.json"
BUILTIN = ROOT / "weebot" / "skills" / "builtin"
TOOL = build_namespaced_name("awwwards", "search_sites")


def _entry():
    return json.loads(CONFIG.read_text(encoding="utf-8"))["awwwards"]


def test_awwwards_runs_pinned_over_stdio_in_the_core_profile():
    entry = _entry()

    assert (entry["transport"], entry["command"]) == ("stdio", "npx")
    assert entry["args"] == ["-y", "awwwards-mcp@1.19.0"]
    assert entry["env"] == {"AWWWARDS_MCP_PROFILE": "core"}


def test_awwwards_is_untrusted_so_every_tool_asks():
    assert _entry().get("trust", "untrusted") == "untrusted"


def test_a_website_step_is_sent_the_awwwards_tools_and_a_weather_step_is_not():
    available = {TOOL, "web_search"}

    assert TOOL in select_tools("Design a landing page for a bakery", available)
    assert TOOL not in select_tools("What is the weather in Athens", available)


def test_senior_frontend_loads_as_a_trusted_imported_skill():
    reg = SkillRegistry(search_paths=[BUILTIN])
    reg.load_all()
    skill = reg.list_all()["senior-frontend"]

    assert skill.metadata.trust == "trusted"
    assert skill.metadata.provenance.origin == "imported"
    assert (BUILTIN / "senior-frontend" / "scripts" / "check_ui.mjs").is_file()


def test_the_web_development_skill_makes_both_part_of_the_workflow():
    text = (BUILTIN / "web-development" / "SKILL.md").read_text(encoding="utf-8")

    assert "mcp__awwwards__" in text
    assert "senior-frontend" in text
    assert "check_ui.mjs" in text
