"""F23 repro: the cost summary query ignores its injected repository.

`GetCostSummaryHandler` takes a state repository but reads a cascade tracker
from a throwaway Container instead, and only echoes `window_hours`. Fixed by
W4.2: the handler reads `EventStorePort.get_cost_window`; see tasks/icm_fix_plan.md.
"""

from unittest.mock import AsyncMock

from weebot.application.cqrs.handlers.active_queries import GetCostSummaryHandler
from weebot.application.cqrs.queries import GetCostSummaryQuery


def _no_container(*_a, **_k):
    raise RuntimeError("no container in this test")


async def test_cost_summary_reads_the_injected_store(monkeypatch):
    monkeypatch.setattr("weebot.application.di.Container", _no_container)
    store = AsyncMock()
    await GetCostSummaryHandler(store).handle(GetCostSummaryQuery(window_hours=6))
    assert store.mock_calls, "handler returned a summary without reading its store"
