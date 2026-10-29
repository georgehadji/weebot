"""R24 (audit 2026-10-29): a fuzzy-matched tool name must meet the egress check.

ToolCollection.execute fuzzy-matched an unknown name (``Advanced_Browser``) to the nearest
tool and ran it, but the executor had already classified egress on the raw name, which
matches no outbound tool. So a misspelt browser submit skipped the egress gate. The name is
now resolved once, before any check, and every stage uses the canonical name.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from weebot.application.agents.executor._tool_executor import ToolExecutor
from weebot.application.models.tool_collection import ToolCollection
from weebot.core.egress_guard import EgressGuard, RecipientAllowlist
from weebot.tools.base import BaseTool, ToolResult


class _Browser(BaseTool):
    name: str = "advanced_browser"
    description: str = "records"
    parameters: dict = {"type": "object", "properties": {}}
    calls: list = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(output="submitted")


def _guard() -> EgressGuard:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    path.write_text(json.dumps({}))
    return EgressGuard(allowlist=RecipientAllowlist(path))


def test_the_collection_resolves_names_once():
    tools = ToolCollection(_Browser())
    assert tools.resolve_name("advanced_browser") == "advanced_browser"
    assert tools.resolve_name("Advanced_Browser") == "advanced_browser"
    assert tools.resolve_name("nothing_like_it") is None


@pytest.mark.asyncio
async def test_execute_runs_only_canonical_names():
    browser = _Browser()
    result = await ToolCollection(browser).execute("Advanced_Browser", action="submit")
    assert result.is_error and "Unknown tool" in result.error
    assert browser.calls == []


@pytest.mark.asyncio
async def test_a_misspelt_browser_submit_meets_the_egress_gate():
    browser = _Browser()
    executor = ToolExecutor(tools=ToolCollection(browser), egress_guard=_guard())
    args = {"action": "submit", "url": "https://first-time.invalid/form"}
    result = await executor.execute_tool("Advanced_Browser", args)
    assert result.is_error and "approval" in result.error
    assert browser.calls == [], "the submit ran without the egress check"


@pytest.mark.asyncio
async def test_a_misspelt_read_still_runs():
    browser = _Browser()
    executor = ToolExecutor(tools=ToolCollection(browser), egress_guard=_guard())
    result = await executor.execute_tool("Advanced_Browser", {"action": "get_text"})
    assert not result.is_error and browser.calls == [{"action": "get_text"}]
