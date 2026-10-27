"""The model router (ACR) learns across runs which models work, ON by default.

Before: the router was rebuilt for every step with no posterior store; outcome writes
went through ``anyio.from_thread.run`` on the event-loop thread and were all dropped;
posteriors were never loaded; and the exploit path ignored them anyway. A shared router
now records each call outcome to SQLite, loads the posteriors once, and lets them move
the ranking.
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from weebot.application.services.routing.adaptive_capability_router import (
    AdaptiveCapabilityRouter,
)
from weebot.core.model_cascade_tracker import CascadeDecision, CascadeOutcome, CascadeTier
from weebot.infrastructure.persistence.posterior_repository import PosteriorRepository


def test_model_learning_is_on_by_default_and_shadow_mode_off():
    import weebot.config.feature_flags as flags

    names = {"WEEBOT_ENABLE_ACR", "WEEBOT_ACR_BANDIT", "WEEBOT_ACR_SHADOW"}
    env = {k: v for k, v in os.environ.items() if k not in names}
    try:
        with patch.dict("os.environ", env, clear=True):
            reloaded = importlib.reload(flags)
            assert reloaded.WEEBOT_ENABLE_ACR is True
            assert reloaded.WEEBOT_ACR_BANDIT is True
            assert reloaded.WEEBOT_ACR_SHADOW is False
    finally:
        importlib.reload(flags)


def _decision(model, outcome=CascadeOutcome.SUCCESS, category="coding"):
    return CascadeDecision(
        model_name=model, tier=CascadeTier.BUDGET, outcome=outcome, latency_ms=1.0,
        task_category=category,
    )


def _router(repo):
    return AdaptiveCapabilityRouter(posterior_repo=repo, force_acr=True, force_bandit=True)


async def test_an_outcome_recorded_on_the_event_loop_reaches_the_store(tmp_path):
    repo = PosteriorRepository(db_path=tmp_path / "acr.db")
    router = _router(repo)
    router.record_cascade_outcome(_decision("m/a"))
    await router.flush()
    assert (await repo.get_all_posteriors())["coding"]["m/a"] == (6.0, 1.0)


async def test_a_model_that_was_never_called_is_not_scored(tmp_path):
    repo = PosteriorRepository(db_path=tmp_path / "acr.db")
    router = _router(repo)
    router.record_cascade_outcome(_decision("m/a", CascadeOutcome.CIRCUIT_OPEN))
    await router.flush()
    assert await repo.get_all_posteriors() == {}


async def test_stored_posteriors_move_the_ranking(tmp_path, monkeypatch):
    from weebot.application.services.routing import adaptive_capability_router as acr

    category = acr.classify_step("write code").value
    repo = PosteriorRepository(db_path=tmp_path / "acr.db")
    for _ in range(30):
        await repo.record_outcome(category, "m/good", True)
        await repo.record_outcome(category, "m/bad", False)

    router = _router(repo)
    await router.ensure_loaded()
    monkeypatch.setattr(router._bandit, "_should_explore", lambda _c: False)

    equal = [MagicMock(model_id="m/bad", score=0.5), MagicMock(model_id="m/good", score=0.5)]
    monkeypatch.setattr(router._checker, "eligible", lambda c, r: c)
    monkeypatch.setattr(router._scorer, "score", lambda c, cat: list(equal))
    assert router.route("write code", candidates=["m/bad", "m/good"])[0] == "m/good"


def test_static_model_is_a_method():
    assert isinstance(AdaptiveCapabilityRouter().static_model("write code"), str)


def test_an_injected_router_drives_step_routing_and_adds_at_most_two_models():
    from weebot.application.agents.executor import ExecutorAgent
    from weebot.application.models.tool_collection import ToolCollection

    router = MagicMock()
    router.route.return_value = ["a/1", "b/2", "c/3", "d/4"]
    executor = ExecutorAgent(llm=MagicMock(), tools=ToolCollection(), acr_router=router)
    assert executor._cascade._acr_router is router
    assert executor._model_for_step("write code") == ["a/1", "b/2"]


async def test_the_cascade_loads_posteriors_before_routing(monkeypatch):
    from weebot.application.agents.executor._cascade import CascadeExecutor

    router = MagicMock()
    router.ensure_loaded = AsyncMock()
    tools = MagicMock()
    tools.to_params.return_value = []
    ex = CascadeExecutor(
        llm=MagicMock(), tools=tools, agent_role=None, model_provider=lambda d: [],
        on_success=None, acr_router=router,
    )
    monkeypatch.setattr(ex, "get_credits_and_filter_direct", AsyncMock(side_effect=RuntimeError("stop")))
    with pytest.raises(RuntimeError):
        await ex.call_with_cascade(messages=[{"role": "user", "content": "x"}], description="d")
    router.ensure_loaded.assert_awaited_once()


@pytest.mark.timeout(360)
def test_the_container_shares_one_learning_router_with_every_step_executor():
    from weebot.application.di import Container
    from weebot.application.di.keys import ACR_ROUTER
    from weebot.domain.models.session import Session

    c = Container()
    c.configure_defaults()
    router = c.get(ACR_ROUTER)
    assert router._posterior_repo is not None
    executor = c.step_executor(model=None, session=Session(id="s-acr"))
    assert executor._cascade._acr_router is router
