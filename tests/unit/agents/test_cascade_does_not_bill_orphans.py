"""D39 — the cascade's failure path billed every probe and discarded successes.

Phase 1 fans out parallel probes and takes the first future to complete.
Cancellation of the losers lived *inside* the `resp is not None` branch, so
the branch where the winner is a failure fell through to Phase 2 with every
other probe still running.

That is not the rare case. `_cascade_try_chat` returns None for every failure
and never raises, and a 429 or 503 comes back in ~200ms against seconds for a
real completion — so the first future to complete is preferentially the
fastest *failure*. Measured on the pre-fix code with five probes, the fastest
failing and two slow ones succeeding:

                    pre-fix   post-fix
    requests sent         5          5
    completions billed    5          3
    cancelled             0          2
    answer returned    none    the success

Pre-fix, both slow probes had *succeeded*. Their responses were discarded and
the cascade fell through to Phase 2 to buy the answer again.

Two facts about asyncio that shape the fix, both verified:

  * a pending task left uncancelled runs to completion — it does not stop
    because nobody is awaiting it;
  * `asyncio.shield` defeats cancellation entirely, so the fix is only sound
    while nothing shields the call.

An honest limit: cancelling aborts the request client-side, but tokens the
provider has already generated may still be billed. This reduces spend; it
does not provably zero it.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.agents.executor._cascade import CascadeExecutor
from weebot.application.ports.llm_port import LLMResponse


class _CountingLLM:
    """Records every call, and whether it ran to completion or was cancelled."""

    def __init__(self, behaviour: dict[str, tuple[float, bool]]) -> None:
        # model -> (delay, succeeds)
        self._behaviour = behaviour
        self.started: list[str] = []
        self.completed: list[str] = []
        self.cancelled: list[str] = []

    async def chat(self, *args, **kwargs):
        model = kwargs.get("model") or (args[1] if len(args) > 1 else "?")
        # An unlisted model FAILS slowly. The first draft defaulted to a fast
        # success, so the role cascade's own default models (pulled in when
        # agent_role is None) won every race and the tests measured them
        # instead of the probes under test.
        delay, succeeds = self._behaviour.get(model, (5.0, False))
        self.started.append(model)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self.cancelled.append(model)
            raise
        self.completed.append(model)
        if not succeeds:
            raise RuntimeError(f"injected failure for {model}")
        return LLMResponse(content=f"ok from {model}", tool_calls=None, usage=None)


def _executor(llm, probes: list[str], monkeypatch) -> CascadeExecutor:
    """A cascade where `probes` ARE the Phase 1 set and Phase 2 is empty.

    This matters, and the first draft of these tests got it wrong. Phase 1
    probes `(role_primary, *acr_models, task_model, role_fallback1)`, while
    Phase 2 tries `(role_fallback2, _TIER4_MODEL)` filtered by `not in
    parallel`. Patching the role cascade to the probe list therefore pushed
    the *successful* model into role_fallback2 — outside Phase 1 — so Phase 2
    called it directly and the tests passed against the unfixed code. They
    discriminated nothing.

    Here the role cascade is a single model that never succeeds, every tier
    constant is that same model, and the probes arrive as the ACR list. Phase
    2's candidates are then all already in `parallel` and it has nothing to
    rescue with, so a success can only come from Phase 1.
    """
    import unittest.mock as m

    # Patched at its source: `_cascade` imports it inside the method, so it
    # never becomes an attribute of that module.
    import weebot.config.model_refs as refs

    monkeypatch.setattr(refs, "get_model_cascade_for_role", lambda role: ["dead/never"])
    monkeypatch.setattr(CascadeExecutor, "_TIER2_MODEL", "dead/never", raising=False)
    monkeypatch.setattr(CascadeExecutor, "_TIER3_MODEL", "dead/never", raising=False)
    monkeypatch.setattr(CascadeExecutor, "_TIER4_MODEL", "dead/never", raising=False)
    monkeypatch.setattr(CascadeExecutor, "get_credits_and_filter_direct", staticmethod(_ident))

    tools = m.MagicMock()
    tools.to_params.return_value = []
    return CascadeExecutor(
        llm=llm,
        tools=tools,
        agent_role=None,
        model_provider=lambda desc: list(probes),
        on_success=None,
    )


@pytest.mark.asyncio
async def test_a_slow_success_is_used_instead_of_escalating(monkeypatch):
    """The defect in one assertion: a probe that succeeded was thrown away.

    The fast probe fails; two slower probes succeed. The cascade must return
    one of the successes rather than fall through to a further paid call.
    """
    llm = _CountingLLM(
        {
            "fast/fails": (0.01, False),
            "slow/works": (0.10, True),
        }
    )
    ex = _executor(llm, ["fast/fails", "slow/works"], monkeypatch)

    resp = await ex.call_with_cascade(messages=[{"role": "user", "content": "hi"}], description="d")

    assert resp is not None, "the cascade discarded a successful probe"
    assert resp.content == "ok from slow/works"


@pytest.mark.asyncio
async def test_no_probe_is_left_running_after_a_winner(monkeypatch):
    """A probe left uncancelled runs to completion and bills.

    REGRESSION GUARD, not a red-before-green case: the success path already
    cancelled its losers, because that was the branch the cancellation lived
    in. This passes against the unfixed code too, and pins the half that
    worked so the fix cannot trade it away.
    """
    llm = _CountingLLM(
        {
            "fast/works": (0.01, True),
            "slow/a": (2.0, True),
            "slow/b": (2.0, True),
        }
    )
    ex = _executor(llm, ["fast/works", "slow/a", "slow/b"], monkeypatch)

    await ex.call_with_cascade(messages=[{"role": "user", "content": "hi"}], description="d")
    await asyncio.sleep(0.05)

    assert "slow/a" not in llm.completed, "a losing probe ran to completion and billed"
    assert "slow/b" not in llm.completed


@pytest.mark.asyncio
async def test_every_probe_failing_leaves_no_probe_unaccounted_for(monkeypatch):
    """Phase 1 exhausts: every probe must reach a terminal state.

    Also passes against the unfixed code, for a reason worth stating: when
    every probe fails they all finish on their own, so there is nothing left
    to orphan. The harvest loop waits for them rather than abandoning them,
    which is the same outcome by a different route. What this pins is that
    neither route leaves a task in flight.

    The first version asserted on `asyncio.all_tasks()` filtered by
    `"chat" in repr(t)`, which never matches a task's repr — it was vacuous
    and would have passed with probes still running.
    """
    llm = _CountingLLM(
        {
            "a/fails": (0.01, False),
            "b/fails": (0.02, False),
            "c/fails": (0.03, False),
        }
    )
    ex = _executor(llm, ["a/fails", "b/fails", "c/fails"], monkeypatch)

    with pytest.raises(Exception):
        await ex.call_with_cascade(
            messages=[{"role": "user", "content": "hi"}], description="d"
        )

    await asyncio.sleep(0.05)
    accounted = set(llm.completed) | set(llm.cancelled)
    unaccounted = [m for m in llm.started if m not in accounted]
    assert unaccounted == [], f"probes neither completed nor cancelled: {unaccounted}"


async def _ident(models):
    return list(models)
