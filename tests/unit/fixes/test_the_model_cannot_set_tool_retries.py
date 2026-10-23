"""A `_max_retries` argument from the model does not change tool retries.

ToolCollection popped `_max_retries` from the call's arguments, which come from
the model, so a model (or injected content) could retry a failing,
side-effecting tool as often as it liked. Nothing in the code passes it.
"""

from __future__ import annotations

from weebot.application.models.tool_collection import ToolCollection
from weebot.tools.base import BaseTool, ToolResult


_CALLS: list = []


class _Flaky(BaseTool):
    name: str = "flaky"
    description: str = "always times out"
    parameters: dict = {"type": "object", "properties": {}}
    async def execute(self, **kwargs) -> ToolResult:
        _CALLS.append(1)
        raise TimeoutError("slow")


async def test_retries_stay_at_the_default(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    tc = ToolCollection(_Flaky())
    result = await tc.execute("flaky", _max_retries=50)
    assert not result.success
    assert len(_CALLS) == ToolCollection.DEFAULT_MAX_RETRIES + 1


async def _no_sleep(*_a, **_k):
    return None
