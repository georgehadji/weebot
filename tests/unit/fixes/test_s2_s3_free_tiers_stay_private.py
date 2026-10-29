"""S2 and S3 (remaining-work plan 2026-10-29): free tiers never see a tainted session.

S2: ``keep_private`` knew only ``free/<provider>/`` ids, so OpenRouter ``:free`` models,
whose free tier may log or train on prompts, were never filtered; and the live-model
rescue did not filter at all. A tainted session whose cascade 404'd could be rescued onto
the cheapest ``:free`` model. S3: the swarm took ``get_model_cascade_for_role(role)[0]`` as
a sub-agent's only model, which is a free model when ``WEEBOT_FREE_ROLES`` names the role:
no fallback for its daily limit and no privacy filter.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.agents.executor._session_scope import get_session_scope, keep_private
from weebot.application.ports.llm_port import LLMResponse
from weebot.config import model_refs
from weebot.config.free_models import trains_on_prompts
from weebot.core.log_context import session_id_var

_FREE = "vendor/model:free"


def test_openrouter_free_tiers_count_as_training():
    assert trains_on_prompts(_FREE) is True
    assert trains_on_prompts("vendor/model") is False


def _tainted(sid: str):
    get_session_scope().mark_tainted(sid)
    return session_id_var.set(sid)


def _untaint(sid: str, token) -> None:
    get_session_scope().close(sid)
    session_id_var.reset(token)


def test_keep_private_drops_free_tiers_in_a_tainted_session():
    token = _tainted("s2-keep")
    try:
        assert keep_private([_FREE, "vendor/paid"]) == ["vendor/paid"]
    finally:
        _untaint("s2-keep", token)


def _rescuer(listing: list[str]) -> CascadeExecutor:
    llm = AsyncMock()
    llm.chat.return_value = LLMResponse(content="rescued", tool_calls=None, usage=None)
    tools = MagicMock()
    tools.to_params.return_value = []
    ex = CascadeExecutor(llm=llm, tools=tools, agent_role="executor", model_provider=None)

    class _Account:
        async def list_models(self):
            return [SimpleNamespace(id=m, supports_tools=True, context_length=200_000) for m in listing]

    ex._provider_account = _Account()
    return ex


@pytest.mark.asyncio
async def test_rescue_never_sends_a_tainted_session_to_a_free_tier():
    ex = _rescuer([_FREE])
    token = _tainted("s2-rescue")
    try:
        assert await ex._live_model_rescue([{"role": "user", "content": "hi"}]) is None
    finally:
        _untaint("s2-rescue", token)
    ex._llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_rescue_may_use_a_free_tier_for_a_clean_session():
    ex = _rescuer([_FREE])
    resp = await ex._live_model_rescue([{"role": "user", "content": "hi"}])
    assert resp is not None and resp.content == "rescued"


def test_a_swarm_sub_agent_never_gets_a_free_model(monkeypatch):
    from weebot.application.agents.hyper_agent import HyperAgent
    from weebot.domain.models.sub_agent import DispatchStrategy
    from weebot.domain.models.swarm import SubGoal, SwarmSpec

    monkeypatch.setattr(
        model_refs, "get_model_cascade_for_role", lambda role: ["free/groq/x", "vendor/paid"]
    )
    agent = HyperAgent(
        llm=None, event_bus=None, swarm_bus=None, sub_agent_factory=None, cost_tracker=None
    )
    specs = agent._specs_from_swarm(
        SwarmSpec(goals=[SubGoal(description="d", role="coder")]), DispatchStrategy.PARALLEL
    )
    assert specs[0].model == "vendor/paid"
