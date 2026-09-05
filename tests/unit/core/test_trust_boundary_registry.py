"""Trust-boundary list must stay in step with the tool registry.

Wave 1 of the V7 defect hunt found ``UNTRUSTED_OUTPUT_TOOLS`` keyed on module
file names rather than ``BaseTool.name`` values. ``browser_tool`` is the module
that registers the tool named ``browser_navigator``; the list matched neither
the fence in ``_base.py`` nor the egress taint in ``_tool_executor.py``, so the
real browser tool's output entered the prompt unfenced *and* left the session
untainted for the egress trifecta check.

The existing trust-boundary tests all assert that a *string* is in the set.
Every one of them passed while the control was off for the tool users actually
call. These tests assert the correspondence instead, so a rename cannot
silently disable the control again.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from weebot.core.egress_guard import _BROWSER_EGRESS_TOOLS
from weebot.core.trust_boundary import UNTRUSTED_OUTPUT_TOOLS, is_untrusted_tool

_TOOLS_DIR = pathlib.Path(__file__).resolve().parents[3] / "weebot" / "tools"


def _registered_tool_names() -> set[str]:
    """Every ``name: str = "..."`` class attribute under weebot/tools.

    Parsed rather than imported: importing every tool drags in optional
    third-party dependencies that need not be installed to check a name.
    """
    names: set[str] = set()
    for path in _TOOLS_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "name"
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                    and stmt.value.value
                ):
                    names.add(stmt.value.value)
    return names


# Registered tools that return content originating outside this process.
# Adding a tool that reaches the network or reads third-party media means
# adding it here AND to UNTRUSTED_OUTPUT_TOOLS.
EXTERNAL_CONTENT_TOOLS = frozenset(
    {
        "web_search",
        "vane_search",
        "advanced_browser",
        "browser_navigator",
        "browser_inspector",
        "web_scraper",
        "spacescraper",
        "search_images",
        "weather",
        "video_ingest",
        "youtube_download",
        "ocr",
        "ocr_structured",
        "screenshot_ocr",
        "atomic_mail",
        "file_editor",
    }
)

# Names kept in UNTRUSTED_OUTPUT_TOOLS that match no registered tool. Retaining
# them is harmless (an unmatched name fences nothing); the point of pinning the
# set is that a *new* unmatched name is a typo until proven otherwise.
KNOWN_UNMATCHED_NAMES = frozenset(
    {
        "browser_tool",  # legacy module-name spelling of browser_navigator
        "browser_inspect",  # documented alias of browser_inspector
        "video_ingest_tool",  # legacy module-name spelling of video_ingest
        "knowledge_tool",  # legacy; "knowledge" is a LOCAL store, not fenced
        "apify_actor_tool",
        "mcp_tool",
        "mcp_call",
        # Gateway tools reserved for channels not yet implemented as BaseTools.
        "discord_tool",
        "email_tool",
        "signal_tool",
        "slack_tool",
        "telegram_tool",
        "whatsapp_tool",
    }
)


class TestRegistryCorrespondence:
    def test_registry_parse_finds_known_tools(self):
        """Guard the guard: a parser returning nothing would pass everything."""
        names = _registered_tool_names()
        assert len(names) > 30, f"tool-name parse looks broken: {sorted(names)}"
        assert {"bash", "browser_navigator", "web_search"} <= names

    @pytest.mark.parametrize("tool", sorted(EXTERNAL_CONTENT_TOOLS))
    def test_every_external_tool_is_fenced(self, tool):
        assert is_untrusted_tool(tool) is True, (
            f"{tool!r} returns external content but is not in "
            f"UNTRUSTED_OUTPUT_TOOLS — its output enters the prompt unfenced "
            f"and does not taint the session for the egress trifecta check."
        )

    def test_external_content_list_names_real_tools(self):
        """EXTERNAL_CONTENT_TOOLS must not drift into naming nonexistent tools."""
        unknown = EXTERNAL_CONTENT_TOOLS - _registered_tool_names()
        assert not unknown, f"not registered BaseTool names: {sorted(unknown)}"

    def test_no_new_unmatched_names(self):
        """A new entry must be a real BaseTool.name, or explicitly grandfathered."""
        unmatched = UNTRUSTED_OUTPUT_TOOLS - _registered_tool_names()
        surprising = unmatched - KNOWN_UNMATCHED_NAMES
        assert not surprising, (
            f"{sorted(surprising)} match no registered tool. Use the "
            f"BaseTool.name value, not the module file name."
        )

    def test_browser_egress_set_names_real_tools(self):
        """EgressGuard carried the same stale spelling as the trust boundary."""
        assert "browser_navigator" in _BROWSER_EGRESS_TOOLS
        unmatched = _BROWSER_EGRESS_TOOLS - _registered_tool_names()
        assert unmatched <= KNOWN_UNMATCHED_NAMES, f"stale: {sorted(unmatched)}"


class TestProofOfDefect:
    """Red before the Wave 1 fix, green after."""

    def test_browser_navigator_is_untrusted(self):
        assert is_untrusted_tool("browser_navigator") is True

    def test_video_ingest_is_untrusted(self):
        assert is_untrusted_tool("video_ingest") is True

    def test_spacescraper_is_untrusted(self):
        assert is_untrusted_tool("spacescraper") is True


class TestBoundaries:
    def test_local_knowledge_store_is_not_fenced(self):
        """"knowledge" persists the agent's own notes via ToolRepositoryPort.

        Fencing it would taint a session for reading back its own memory and
        make every later egress require approval.
        """
        assert is_untrusted_tool("knowledge") is False

    def test_local_execution_tools_are_not_fenced(self):
        for tool in ("bash", "python_execute", "powershell", "terminate", "ask_human"):
            assert is_untrusted_tool(tool) is False, tool

    def test_unknown_tool_is_not_fenced(self):
        assert is_untrusted_tool("some_tool_that_does_not_exist") is False
