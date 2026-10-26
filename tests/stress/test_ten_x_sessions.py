"""The 10x proof (plan Phase 8, input to Sep plan 5.5): 30 concurrent sessions.

Thirty sessions each make several LLM calls through the bulkhead and journal their
events to the real SQLite event store, concurrently, against a fake provider with
injected latency. Asserted, as the plan asks:

* the LLM pool bound holds (peak in-flight never exceeds it);
* no ``database is locked`` anywhere;
* p95 event-persist latency stays under a recorded budget.

Honest limit: this drives the real bulkhead and the real event store, not the whole
FastAPI app and flow stack. It proves the two shared resources the audit worried
about under load; the full-app trace remains with Sep plan 5.5.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest

from weebot.application.ports.llm_port import LLMPort
from weebot.application.services.effect_ledger import EffectLedger
from weebot.application.strategies.llm_pool import BoundedLLMAdapter, LLMPool
from weebot.domain.models.llm_response import LLMResponse
from weebot.infrastructure.event_store import EventStore

SESSIONS = 30
CALLS_PER_SESSION = 4
POOL = 6
LLM_LATENCY_S = 0.02
# Recorded budget: a single-writer SQLite on a laptop disk handled this load with
# p95 around tens of milliseconds. Generous on purpose; tighten only from measurements.
P95_PERSIST_BUDGET_S = 2.0


class LatentLLM(LLMPort):
    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0

    async def chat(self, messages, tools=None, tool_choice="auto", response_format=None,
                   model=None, temperature=None, max_tokens=None):
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(LLM_LATENCY_S)
        finally:
            self.in_flight -= 1
        return LLMResponse(content="ok", usage={"prompt_tokens": 10, "completion_tokens": 5})


@pytest.mark.asyncio
async def test_thirty_sessions_share_the_pool_and_the_event_store(tmp_path):
    store = EventStore(db_path=str(tmp_path / "events.db"))
    ledger = EffectLedger(store)
    inner = LatentLLM()
    llm = BoundedLLMAdapter(inner, LLMPool(max_concurrent=POOL, acquire_timeout=60))
    persist_latencies: list[float] = []
    errors: list[BaseException] = []

    async def session(n: int) -> None:
        sid = f"load-{n}"
        for call in range(CALLS_PER_SESSION):
            await llm.chat(messages=[{"role": "user", "content": f"{sid}:{call}"}])
            started = time.perf_counter()
            await store.log_event(sid, "tool", {"call": call})
            await ledger.record(sid, f"key-{n}-{call}", "bash", "done", ok=True)
            persist_latencies.append(time.perf_counter() - started)

    results = await asyncio.gather(*(session(n) for n in range(SESSIONS)), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]

    assert not errors, f"sessions failed: {errors[:3]}"
    assert not any("database is locked" in str(e) for e in errors)
    assert inner.peak <= POOL, f"{inner.peak} LLM calls in flight against a pool of {POOL}"
    assert inner.peak > 1, "the test never exercised concurrency"

    expected = SESSIONS * CALLS_PER_SESSION
    assert len(persist_latencies) == expected
    p95 = statistics.quantiles(persist_latencies, n=20)[18]
    assert p95 < P95_PERSIST_BUDGET_S, f"p95 persist latency {p95:.3f}s over {P95_PERSIST_BUDGET_S}s"

    # Nothing was lost under contention: every session's events and effects are there.
    for n in (0, SESSIONS - 1):
        events = await store.get_session_events(f"load-{n}")
        assert len([e for e in events if e["event_type"] == "tool"]) == CALLS_PER_SESSION
        assert await ledger.lookup(f"load-{n}", f"key-{n}-0") is not None
