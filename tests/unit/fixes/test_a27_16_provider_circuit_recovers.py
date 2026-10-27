"""A16: once the direct provider's circuit opened it never closed, so every later call
went to OpenRouter for the life of the process, even after the provider recovered."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from weebot.application.ports.llm_port import LLMResponse
from weebot.infrastructure.adapters.llm.direct_or_fallback_adapter import (
    DirectOrFallbackAdapter,
)


class _Fake:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name, self.fail, self.calls = name, fail, 0
        self._client = SimpleNamespace(api_key="sk-test")

    async def chat(self, **_kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} down")
        return LLMResponse(content=self.name, tool_calls=[], usage={}, model=self.name)


def _adapter(primary, secondary, cooldown=0.05):
    adapter = DirectOrFallbackAdapter(primary, secondary, primary_label="t")
    adapter._COOLDOWN_S = cooldown
    adapter._rebuild_breaker()
    return adapter


async def _ask(adapter):
    return (await adapter.chat(messages=[{"role": "user", "content": "hi"}])).content


async def test_an_open_circuit_skips_the_primary():
    primary, secondary = _Fake("primary", fail=True), _Fake("secondary")
    adapter = _adapter(primary, secondary, cooldown=60)
    for _ in range(3):
        assert await _ask(adapter) == "secondary"
    calls_when_open = primary.calls
    assert await _ask(adapter) == "secondary"
    assert primary.calls == calls_when_open


async def test_the_primary_is_probed_again_after_the_cooldown_and_recovers():
    primary, secondary = _Fake("primary", fail=True), _Fake("secondary")
    adapter = _adapter(primary, secondary, cooldown=0.05)
    for _ in range(3):
        await _ask(adapter)
    primary.fail = False
    await asyncio.sleep(0.1)
    assert await _ask(adapter) == "primary"
    assert await _ask(adapter) == "primary"  # closed again, not stuck on the fallback


async def test_a_failed_probe_reopens_the_circuit():
    primary, secondary = _Fake("primary", fail=True), _Fake("secondary")
    adapter = _adapter(primary, secondary, cooldown=0.05)
    for _ in range(3):
        await _ask(adapter)
    await asyncio.sleep(0.1)
    assert await _ask(adapter) == "secondary"  # the probe failed, fallback answered
    before = primary.calls
    assert await _ask(adapter) == "secondary"
    assert primary.calls == before


@pytest.mark.parametrize("fails", [0, 1, 2])
async def test_fewer_failures_than_the_threshold_keep_it_closed(fails):
    primary, secondary = _Fake("primary", fail=True), _Fake("secondary")
    adapter = _adapter(primary, secondary)
    for _ in range(fails):
        await _ask(adapter)
    primary.fail = False
    assert await _ask(adapter) == "primary"
