"""Claude models: only Opus 5.5, Sonnet 5.5 and Haiku 5.5; never Fable.

User rule, 2026-10-23. The routed role table already met it, but two paths
could reach any Claude model: `MODEL_FACTORY_ANTHROPIC` named Sonnet 5, and
the cascade's live-model rescue took the paid tool-capable model with the
largest context from the live list -- which can be a Fable model at
$10/$50 per million tokens.
"""

from __future__ import annotations

import pytest

import weebot.config.model_refs as refs
from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.provider_account_port import ModelListing
from weebot.domain.models.llm_response import LLMResponse


def _all_ref_ids() -> set[str]:
    ids: set[str] = set()
    for name in dir(refs):
        if not name.isupper():
            continue
        value = getattr(refs, name)
        values = value.values() if isinstance(value, dict) else [value]
        for v in values:
            if isinstance(v, str):
                ids.add(v)
            elif isinstance(v, (list, tuple, set, frozenset)):
                ids.update(x for x in v if isinstance(x, str))
    return ids


@pytest.mark.parametrize(
    ("model", "allowed"),
    [
        ("anthropic/claude-opus-5.5", True),
        ("anthropic/claude-sonnet-5.5", True),
        ("anthropic/claude-haiku-5.5", True),
        ("claude-sonnet-5-5", True),  # the direct-API spelling
        ("anthropic/claude-fable-5.1", False),
        ("anthropic/claude-sonnet-5", False),
        ("anthropic/claude-opus-4.8", False),
        ("deepseek/deepseek-v4.1-flash", True),  # the rule covers Claude only
    ],
)
def test_the_rule(model, allowed):
    assert refs.claude_model_allowed(model) is allowed


def test_every_model_ref_obeys_the_rule():
    bad = sorted(m for m in _all_ref_ids() if "claude" in m and not refs.claude_model_allowed(m))
    assert bad == []


def test_the_acr_pool_obeys_the_rule():
    from weebot.application.services.routing.adaptive_capability_router import (
        default_candidate_pool,
    )

    assert all(refs.claude_model_allowed(m) for m in default_candidate_pool())


class _Account:
    async def list_models(self):
        return [
            ModelListing(
                id="anthropic/claude-fable-5.1", context_length=1_000_000, supports_tools=True
            ),
            ModelListing(
                id="anthropic/claude-haiku-5.5", context_length=200_000, supports_tools=True
            ),
        ]


class _LLM:
    def __init__(self):
        self.models: list[str] = []

    async def chat(self, *a, model=None, **kw):
        self.models.append(model)
        return LLMResponse(content="ok", tool_calls=None, usage=None)


@pytest.mark.asyncio
async def test_live_rescue_never_picks_a_forbidden_claude_model():
    from unittest.mock import MagicMock

    llm = _LLM()
    tools = MagicMock()
    tools.to_params.return_value = []
    ex = CascadeExecutor(llm=llm, tools=tools, provider_account=_Account())
    await ex._live_model_rescue([{"role": "user", "content": "hi"}])
    assert llm.models and "fable" not in llm.models[0]
