"""`ToolCollection.teardown` closes the browser the browser tools share.

Teardown only shut down `apify_service`; it never called `BaseTool.close()`, and
neither browser tool overrode it. Every flow that browsed left its Chromium
running until the process exited (Wave G browser card, defect 1).
"""

from __future__ import annotations

from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.advanced_browser import AdvancedBrowserTool
from weebot.tools.browser_inspector import BrowserInspectorTool


class _Adapter:
    def __init__(self):
        self.closed = 0
        self.page = None

    async def close(self):
        self.closed += 1


async def test_teardown_closes_the_shared_browser():
    adapter = _Adapter()
    tools = ToolCollection(
        AdvancedBrowserTool(browser=adapter), BrowserInspectorTool(browser=adapter)
    )
    await tools.teardown()
    assert adapter.closed >= 1


async def test_teardown_survives_a_tool_whose_close_fails():
    class _Bad(_Adapter):
        async def close(self):
            raise RuntimeError("stuck")

    good = _Adapter()
    tools = ToolCollection(AdvancedBrowserTool(browser=_Bad()), BrowserInspectorTool(browser=good))
    await tools.teardown()
    assert good.closed == 1


async def test_teardown_reaches_a_guarded_tools_service():
    # Paid tools are wrapped in GuardedTool (F54); teardown looked for
    # apify_service on the wrapper, so Apify's aiohttp sessions stayed open.
    from unittest.mock import AsyncMock, MagicMock

    from weebot.application.services.tool_guards import GuardChain, GuardedTool
    from weebot.domain.models.base_tool import BaseTool
    from weebot.domain.models.tool_result import ToolResult

    class _Paid(BaseTool):
        async def execute(self, **kw):
            return ToolResult(output="ok")

    inner = _Paid(name="apify_x", description="d", parameters={"type": "object", "properties": {}})
    svc = MagicMock()
    svc.shutdown = AsyncMock()
    object.__setattr__(inner, "apify_service", svc)
    tools = ToolCollection(GuardedTool.wrap(inner, GuardChain([]), "enforce", None))
    await tools.teardown()
    svc.shutdown.assert_awaited_once()
