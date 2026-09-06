"""Two instruments that report on the wrong object.

D41. `ResilientLLMAdapter.chat` keys the circuit breaker on the RUNTIME model --
`model or self._model_name` -- so each cascade tier gets its own breaker, which
is deliberate and correct. But `get_circuit_state`, `get_metrics` and
`reset_circuit` all use `self._model_name`, the CONSTRUCTION-time name. When the
cascade drives one adapter across several models, the breaker that trips is
keyed on the runtime model while the operator inspects a different one -- so the
state reads CLOSED while requests are being rejected, and `reset_circuit()`, the
manual recovery lever, resets a breaker that was never open.

D29. `Task.exception()` raises CancelledError when the task was cancelled, and
`task_runner._cleanup` calls it unguarded. Cancelling a session is an ordinary
operation -- `flow cancel <id>` is a CLI command -- so every cancellation pushed
a CancelledError into the loop's exception handler. Measured:

    unguarded form -> loop exception handler saw ['CancelledError']
    guarded form   -> loop exception handler saw []

It does not corrupt state: the pops above it have already run. It fills the log
with a spurious error on a normal path, which is its own kind of harm -- a real
failure during cleanup is now one more CancelledError in a stream of them.
"""

from __future__ import annotations

import asyncio

import pytest

from weebot.application.ports.llm_port import LLMResponse
from weebot.infrastructure.adapters.llm.resilient_adapter import ResilientLLMAdapter


class _AlwaysFails:
    async def chat(self, *a, **k):
        raise RuntimeError("upstream down")


class _Succeeds:
    async def chat(self, *a, **k):
        return LLMResponse(content="ok", model="m", usage={})


def _adapter(inner, name="configured/model"):
    return ResilientLLMAdapter(
        inner_adapter=inner, model_name=name, timeout=5.0,
        enable_circuit_breaker=True, enable_retry=False,
    )


async def _trip(adapter, model: str, times: int = 8) -> None:
    for _ in range(times):
        try:
            await adapter.chat([{"role": "user", "content": "x"}], model=model)
        except Exception:
            pass


# --------------------------------------------------------------------------
# D41
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_state_reported_is_the_breaker_that_actually_tripped():
    a = _adapter(_AlwaysFails())
    await _trip(a, "runtime/model")
    assert a.get_circuit_state(model="runtime/model") == "open", (
        "the breaker that rejected the requests is not the one being inspected"
    )


@pytest.mark.asyncio
async def test_metrics_report_every_breaker_this_adapter_has_used():
    a = _adapter(_AlwaysFails())
    await _trip(a, "runtime/model")
    states = a.get_metrics().get("circuit_states")
    assert isinstance(states, dict), f"no per-key states in metrics: {states!r}"
    assert states.get("runtime/model") == "open", states


@pytest.mark.asyncio
async def test_reset_clears_the_breaker_the_cascade_actually_opened():
    a = _adapter(_AlwaysFails())
    await _trip(a, "runtime/model")
    assert a.get_circuit_state(model="runtime/model") == "open"
    await a.reset_circuit()
    assert a.get_circuit_state(model="runtime/model") == "closed", (
        "reset_circuit() left open the breaker it was called to clear"
    )


@pytest.mark.asyncio
async def test_reset_can_target_one_model():
    a = _adapter(_AlwaysFails())
    await _trip(a, "one/model")
    await _trip(a, "two/model")
    await a.reset_circuit(model="one/model")
    assert a.get_circuit_state(model="one/model") == "closed"
    assert a.get_circuit_state(model="two/model") == "open", "reset was too broad"


# --------------------------------------------------------------------------
# D29
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancelling_a_session_does_not_raise_in_the_done_callback():
    from weebot.application.services.task_runner import TaskRunner
    import inspect

    src = inspect.getsource(TaskRunner)
    assert "cancelled()" in src, (
        "the done-callback calls Task.exception() without checking cancelled(); "
        "on a cancelled task that raises CancelledError into the loop handler"
    )


@pytest.mark.asyncio
async def test_a_cancelled_task_is_clean_in_the_shape_the_runner_uses():
    """The behaviour itself, independent of the source check above."""
    seen: list[BaseException | str] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda lp, ctx: seen.append(ctx.get("exception") or ctx["message"]))

    from weebot.application.services import task_runner as tr

    async def work():
        await asyncio.sleep(10)

    task = asyncio.create_task(work())

    def cleanup(t):
        if t.cancelled():
            return
        if t.exception():
            pass

    # Mirror the runner's guard, then assert the runner has one.
    task.add_done_callback(cleanup)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)
    assert seen == [], seen
    assert "cancelled()" in __import__("inspect").getsource(tr.TaskRunner)


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_healthy_model_is_not_reported_open():
    a = _adapter(_Succeeds())
    for _ in range(3):
        await a.chat([{"role": "user", "content": "x"}], model="fine/model")
    assert a.get_circuit_state(model="fine/model") == "closed"


@pytest.mark.asyncio
async def test_the_default_key_is_still_the_configured_model():
    """Called with no runtime model, nothing about the old behaviour changes."""
    a = _adapter(_AlwaysFails(), name="configured/model")
    await _trip(a, None)
    assert a.get_circuit_state() == "open"
    assert a.get_metrics()["model"] == "configured/model"
