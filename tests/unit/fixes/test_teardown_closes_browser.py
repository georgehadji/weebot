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
