"""ORCH-1: one bound on in-flight LLM calls, whichever path makes them.

Plan item 2.1 of tasks/specs/arch_audit_2026_10_remediation_plan.md. The pool
used to bound only the cascade; direct callers (planner, optimizer, verifiers)
ran unbounded. These tests drive both paths through one pool at once.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from weebot.application.di.keys import LLM_POOL

from weebot.application.ports.llm_port import LLMPort
from weebot.application.strategies.llm_pool import (
    BoundedLLMAdapter,
    LLMPool,
    unwrap_llm,
)
from weebot.domain.exceptions import LLMCapacityExhaustedError
from weebot.domain.models.llm_response import LLMResponse

_ROOT = pathlib.Path(__file__).resolve().parents[2]


class CountingLLM(LLMPort):
    """Counts in-flight calls and records the high-water mark."""

    def __init__(self, hold: float = 0.01) -> None:
        self.in_flight = 0
        self.peak = 0
        self.calls = 0
        self._hold = hold

    async def chat(self, messages, tools=None, tool_choice="auto", response_format=None,
                   model=None, temperature=None, max_tokens=None) -> LLMResponse:
        self.in_flight += 1
        self.calls += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self._hold)
        finally:
            self.in_flight -= 1
        return LLMResponse(content="ok")


async def _call(llm: LLMPort) -> None:
    await llm.chat(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("k", [1, 2, 4])
async def test_three_k_callers_across_both_paths_never_exceed_k(k):
    pool = LLMPool(max_concurrent=k, acquire_timeout=30)
    inner = CountingLLM()
    bounded = BoundedLLMAdapter(inner, pool)

    async def cascade_style():
        # The cascade acquires the pool itself, then calls the (bounded) port.
        async with pool:
            await _call(bounded)

    jobs = [_call(bounded) if i % 2 else cascade_style() for i in range(3 * k)]
    await asyncio.gather(*jobs)

    assert inner.calls == 3 * k
    assert inner.peak <= k, f"{inner.peak} calls in flight with a pool of {k}"
    assert pool.available == k, "every slot must come back"


@pytest.mark.asyncio
async def test_an_admitted_call_does_not_take_a_second_slot_at_pool_size_one():
    """The nested-acquire deadlock the admission token exists to prevent."""
    pool = LLMPool(max_concurrent=1, acquire_timeout=2)
    bounded = BoundedLLMAdapter(CountingLLM(), pool)

    async def admitted():
        async with pool:  # the cascade's acquire, outside its wait_for
            await asyncio.wait_for(_call(bounded), timeout=1)  # new task, same context

    await asyncio.wait_for(admitted(), timeout=3)
    assert pool.available == 1


@pytest.mark.asyncio
async def test_saturation_raises_capacity_exhausted_not_timeout():
    pool = LLMPool(max_concurrent=1, acquire_timeout=0.05)
    inner = CountingLLM(hold=0.3)
    bounded = BoundedLLMAdapter(inner, pool)

    holder = asyncio.create_task(_call(bounded))
    await asyncio.sleep(0.02)
    with pytest.raises(LLMCapacityExhaustedError):
        await _call(bounded)
    await holder


@pytest.mark.asyncio
async def test_an_unrelated_task_does_not_inherit_a_slot():
    """The admission token follows the call, not the process."""
    pool = LLMPool(max_concurrent=1, acquire_timeout=0.05)
    inner = CountingLLM(hold=0.2)
    bounded = BoundedLLMAdapter(inner, pool)

    async with pool:
        outsider = asyncio.create_task(_call(bounded))  # created INSIDE: inherits the token
        await outsider
        assert inner.calls == 1

    # Started from a context with no slot, with the pool full: must queue and refuse.
    holder = asyncio.create_task(_call(bounded))
    await asyncio.sleep(0.02)
    with pytest.raises(LLMCapacityExhaustedError):
        await _call(bounded)
    await holder


@pytest.mark.asyncio
async def test_a_failing_call_returns_its_slot():
    pool = LLMPool(max_concurrent=1, acquire_timeout=1)

    class Boom(CountingLLM):
        async def chat(self, *a, **k):
            raise RuntimeError("provider 500")

    bounded = BoundedLLMAdapter(Boom(), pool)
    with pytest.raises(RuntimeError):
        await _call(bounded)
    assert pool.available == 1


@pytest.mark.asyncio
async def test_streaming_holds_a_slot_for_the_whole_stream():
    pool = LLMPool(max_concurrent=1, acquire_timeout=0.05)
    seen_available: list[int] = []

    class Streaming(CountingLLM):
        async def stream(self, messages, **kwargs):
            for _ in range(3):
                seen_available.append(pool.available)
                yield "chunk"
                await asyncio.sleep(0)

    bounded = BoundedLLMAdapter(Streaming(), pool)
    assert [c async for c in bounded.stream([{"role": "user", "content": "x"}])] == ["chunk"] * 3
    assert seen_available == [0, 0, 0]
    assert pool.available == 1


def test_a_non_streaming_adapter_is_not_mistaken_for_a_streaming_one():
    from weebot.application.ports.streaming_llm_port import StreamingLLMPort

    bounded = BoundedLLMAdapter(CountingLLM(), LLMPool(max_concurrent=1))
    assert not isinstance(bounded, StreamingLLMPort)


def test_adapter_specific_attributes_pass_through_and_unwrap_finds_the_adapter():
    inner = CountingLLM()
    inner.get_metrics = lambda: {"ok": True}  # type: ignore[attr-defined]
    bounded = BoundedLLMAdapter(inner, LLMPool(max_concurrent=1))
    assert bounded.get_metrics() == {"ok": True}
    assert unwrap_llm(BoundedLLMAdapter(bounded, LLMPool(max_concurrent=1))) is inner
    with pytest.raises(AttributeError):
        bounded.not_a_real_attribute  # noqa: B018


class TestTheContainerBoundsEveryLLMItHandsOut:
    def test_default_and_role_llms_are_bounded(self):
        from weebot.application.di import Container

        container = Container()
        container.configure_defaults()
        pool = container.get(LLM_POOL)

        for llm in (container.get(LLMPort), container._create_llm_for_role("critic")):
            assert isinstance(llm, BoundedLLMAdapter)
            assert llm.pool is pool, "one process-wide pool, not one per adapter"

    def test_every_adapter_the_di_package_builds_goes_through_the_bulkhead(self):
        """No `create_adapter(...)` in application/di may return an unwrapped client."""
        offenders = []
        for path in sorted((_ROOT / "weebot" / "application" / "di").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = {
                    getattr(n.func, "id", getattr(n.func, "attr", ""))
                    for n in ast.walk(func)
                    if isinstance(n, ast.Call)
                }
                if "create_adapter" in calls and "_bounded_llm" not in calls:
                    offenders.append(f"{path.name}:{func.name}")
        assert not offenders, f"these build an LLM client without the bulkhead: {offenders}"
