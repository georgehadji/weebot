"""Every routable model id gets an adapter.

Found 2026-10-23 by a live probe of the role table: `ModelProvider.from_model_name`
maps `google/...` to "google" (and `poolside/...`, `microsoft/...` to their own
names), but `AdapterFactory._create_inner_adapter` has no branch for them and
raised "Unknown provider: google". Any role or fallback whose model carried one
of those prefixes could not be built. A `vendor/model` id with no direct adapter
is an OpenRouter id, so it goes to OpenRouter.
"""

from __future__ import annotations

import pytest

from weebot.config.model_refs import MODEL_FALLBACK_OPENROUTER_CHAIN, ROLE_MODEL_CONFIG
from weebot.config.model_registry import ModelProvider
from weebot.infrastructure.adapters.llm.adapter_factory import create_adapter

ROUTED = sorted(
    {m for ms in ROLE_MODEL_CONFIG.values() for m in ms} | set(MODEL_FALLBACK_OPENROUTER_CHAIN)
)


@pytest.mark.parametrize("model", ROUTED)
def test_every_routed_model_builds_an_adapter(model):
    provider = ModelProvider.from_model_name(model).value
    assert create_adapter(provider, model=model) is not None


@pytest.mark.parametrize("model", ["google/gemini-4-argon", "poolside/laguna-xs-2.1"])
def test_a_vendor_prefix_without_a_direct_adapter_uses_openrouter(model):
    provider = ModelProvider.from_model_name(model).value
    from weebot.infrastructure.adapters.llm.openrouter_adapter import OpenRouterAdapter

    adapter = create_adapter(provider, model=model)
    assert isinstance(getattr(adapter, "_inner", adapter), OpenRouterAdapter)
