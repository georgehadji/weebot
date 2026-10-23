"""W4.2 (F23): one cost query, read from the event store.

Before this, GetCostSummaryHandler read a cascade tracker from a throwaway
Container (always empty) and echoed window_hours, CLI `costs` printed
placeholder rows, and MCP `weebot://costs` was a stub because nothing passed it
a tracker. Now EventStorePort.get_cost_window sums the llm_call_completed rows
(W4.1), GetCostSummaryHandler returns that, and CLI and MCP call the handler.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from weebot.application.cqrs.handlers.active_queries import GetCostSummaryHandler
from weebot.application.cqrs.queries import GetCostSummaryQuery
from weebot.infrastructure.event_store import AsyncEventStore


async def _store_with_calls(tmp_path) -> AsyncEventStore:
    store = AsyncEventStore(db_path=str(tmp_path / "events.db"))
    await store.log_event("s1", "llm_call_completed", {}, cost=0.10, model="a", tokens_used=100)
    await store.log_event("s1", "llm_call_completed", {}, cost=0.20, model="a", tokens_used=50)
    await store.log_event("s2", "llm_call_completed", {}, cost=0.05, model="b", tokens_used=10)
    await store.log_event("s2", "step", {"x": 1})  # not a call: no cost
    old = await store.log_event("s3", "llm_call_completed", {}, cost=9.0, model="a", tokens_used=1)
    pool = await store._get_pool()
    async with pool.acquire_write() as conn:
        await conn.execute(
            "UPDATE events SET timestamp = datetime('now', '-3 days') WHERE id = ?", (old,)
        )
    return store


async def test_the_store_sums_llm_calls_inside_the_window(tmp_path):
    store = await _store_with_calls(tmp_path)
    summary = await store.get_cost_window(24)
    assert summary["calls"] == 3
    assert round(summary["total_cost"], 6) == 0.35 and summary["total_tokens"] == 160
    a = summary["by_model"]["a"]
    assert (round(a["cost"], 6), a["tokens"], a["calls"]) == (0.3, 150, 2)
    week = await store.get_cost_window(24 * 7)
    assert week["calls"] == 4


async def test_the_handler_answers_from_the_store(tmp_path):
    store = await _store_with_calls(tmp_path)
    result = await GetCostSummaryHandler(store).handle(GetCostSummaryQuery(window_hours=24))
    assert result.success, result.error
    assert result.data["calls"] == 3 and result.data["window_hours"] == 24


async def test_mcp_costs_resource_uses_the_same_query(tmp_path):
    from weebot.mcp.resources import build_costs_json

    store = await _store_with_calls(tmp_path)
    data = json.loads(await build_costs_json(event_store=store))
    assert data["calls"] == 3 and data["window_hours"] == 24


def test_cli_costs_prints_store_totals_not_placeholders(monkeypatch, tmp_path):
    import asyncio

    import cli.main as cli_main

    store = asyncio.run(_store_with_calls(tmp_path))
    monkeypatch.setattr(cli_main, "_event_store", lambda: store)
    result = CliRunner().invoke(cli_main.cli, ["costs", "--days", "1"])
    assert result.exit_code == 0, result.output
    assert "$2.45" not in result.output
    assert "0.3500" in result.output and "160" in result.output
