"""Cascade telemetry labels each model by its own tier.

Phase 1 labelled every probe FREE (the role primaries are paid), and phase 2
zipped models with labels by position, so a filtered fallback shifted them.
"""

from __future__ import annotations

import types

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.models.tool_collection import ToolCollection
from weebot.core.model_cascade_tracker import CascadeTier


async def test_a_premium_probe_is_labelled_premium(monkeypatch):
    cascade = CascadeExecutor(llm=object(), tools=ToolCollection(), agent_role="executor",
                              pinned_model="anthropic/claude-opus-5.5")
    tiers = []

    async def _try(messages, model, *a, tier=None, **k):
        tiers.append((model, tier))
        return types.SimpleNamespace(content="ok", model=model, usage=None)

    async def _no_filter(models):
        return models

    monkeypatch.setattr(cascade, "_cascade_try_chat", _try)
    monkeypatch.setattr(cascade, "get_credits_and_filter_direct", _no_filter)
    await cascade.call_with_cascade([{"role": "user", "content": "hi"}], "x")
    assert tiers[0] == ("anthropic/claude-opus-5.5", CascadeTier.PREMIUM)


def test_free_and_budget_ids():
    assert CascadeExecutor._tier_of("vendor/m:free") == CascadeTier.FREE
    assert CascadeExecutor._tier_of("deepseek/deepseek-v4.1-flash-1017") == CascadeTier.BUDGET
