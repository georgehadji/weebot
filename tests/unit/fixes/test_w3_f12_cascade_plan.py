"""F12: the cascade must try every cheap model before the premium one.

Phase 1 took `role_cascade[0..1]` and phase 2 took `role_cascade[2]` and the premium model, so
entries from index 3 on were never tried, and an Ollama or free model prepended to the list
shifted paid models out of their slots. The order is now one pure function of the whole list.
"""

from __future__ import annotations

import unittest.mock as m

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse
from weebot.core.cascade_plan import CascadePlan, build_cascade_plan

T2, T3, P = "tier2/m", "tier3/m", "premium/m"


def _plan(role, **kw) -> CascadePlan:
    return build_cascade_plan(role, tier2=T2, tier3=T3, tier4=P, **kw)


def test_three_entries_behave_as_they_always_did():
    plan = _plan(["a", "b", "c"])
    assert (plan.probes, plan.fallbacks) == (("a", "b"), ("c", P))


def test_a_fourth_cheap_model_is_tried_before_the_premium_one():
    plan = _plan(["a", "b", "c", "d"])
    assert plan.fallbacks == ("c", "d", P)


def test_a_fifth_is_tried_too():
    assert _plan(["a", "b", "c", "d", "e"]).fallbacks == ("c", "d", "e", P)


def test_a_prepended_local_model_does_not_push_a_paid_one_out():
    plan = _plan(["ollama/x", "a", "b", "c", "d"])
    assert plan.probes == ("ollama/x", "a")
    assert plan.fallbacks == ("b", "c", "d", P)


def test_the_premium_model_is_last_even_when_the_role_list_holds_it():
    plan = _plan(["a", "b", P, "d"])
    assert plan.fallbacks == ("d", P)


def test_short_lists_fall_back_to_the_tier_defaults():
    assert _plan(["a"]) == CascadePlan(probes=("a", T2), fallbacks=(T3, P))
    assert _plan(["a", "b"]) == CascadePlan(probes=("a", "b"), fallbacks=(T3, P))
    assert _plan([]) == CascadePlan(probes=(T2,), fallbacks=(T3, P))


def test_pinned_and_extra_probes_come_first_and_every_name_appears_once():
    plan = _plan(["a", "b", "c"], pinned="pin", extra_probes=("x", None, "a", "y"))
    assert plan.probes == ("pin", "a", "x", "y", "b")
    assert plan.fallbacks == ("c", P)


@pytest.mark.parametrize("n", range(0, 8))
def test_no_name_repeats_within_a_phase_and_premium_ends_the_plan(n):
    plan = _plan([f"m{i}" for i in range(n)] + ["m0", P])
    assert len(set(plan.probes)) == len(plan.probes)
    assert len(set(plan.fallbacks)) == len(plan.fallbacks)
    assert plan.fallbacks[-1] == P


# ── the shell runs the plan ─────────────────────────────────────────────────


async def test_the_cascade_reaches_the_fourth_model_before_paying_for_premium(monkeypatch):
    import weebot.config.model_refs as refs

    role = ["m/a", "m/b", "m/c", "m/d"]
    monkeypatch.setattr(refs, "get_model_cascade_for_role", lambda _role: role)
    monkeypatch.setattr(CascadeExecutor, "_TIER4_MODEL", P, raising=False)

    async def _ident(models, *a, **k):
        return models

    monkeypatch.setattr(CascadeExecutor, "get_credits_and_filter_direct", staticmethod(_ident))
    called: list[str] = []

    class _Llm:
        async def chat(self, **kw):
            called.append(kw["model"])
            if kw["model"] != "m/d":
                raise RuntimeError("503 overloaded")
            return LLMResponse(content="ok", tool_calls=None, usage=None)

    tools = m.MagicMock()
    tools.to_params.return_value = []
    ex = CascadeExecutor(llm=_Llm(), tools=tools, agent_role="executor")
    ex._HEDGE_DELAY_S = 0.0
    reply = await ex.call_with_cascade([{"role": "user", "content": "x"}], "d")

    assert reply.content == "ok"
    assert "m/d" in called and P not in called
