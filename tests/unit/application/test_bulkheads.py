"""Phase 1.3 -- bulkheads: a bound on running flows, and a bound on LLM calls.

``tasks/specs/arch_audit_2026_09_remediation_plan.md``. Both bounds existed on
paper before this. ``LLMPool`` was registered in the container and never passed
to anything; ``TaskRunner``'s queue had a ``maxsize`` on a path nothing in the
product calls. So none of the behaviour below had ever executed.

The plan asked for a load test before wiring the pool, because wiring it turns
on code that has never run. A live load test means billed calls against real
providers, so these tests drive the mechanism under contention with fakes
instead, and assert the properties that matter:

* the bound actually holds under concurrency;
* saturation is its own error, never a model timeout;
* time spent queuing is never charged to a model;
* a retry at capacity cannot deadlock against itself;
* the pool reaches the executor that actually runs steps -- which is not the
  one the plan named.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from weebot.application.strategies.llm_pool import LLMPool
from weebot.domain.exceptions import LLMCapacityExhaustedError
from weebot.domain.models.llm_response import LLMResponse

# ═════════════════════════════════════════════════════════════════════════════
# LLMPool
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_in_flight_calls_never_exceed_the_pool():
    pool = LLMPool(max_concurrent=3)
    in_flight = 0
    peak = 0

    async def call():
        nonlocal in_flight, peak
        async with pool:
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    await asyncio.gather(*(call() for _ in range(40)))

    assert peak == 3, f"peak in-flight was {peak} against a bound of 3"
    assert pool.available == 3, "a slot leaked"


@pytest.mark.asyncio
async def test_saturation_raises_its_own_error_and_it_is_not_a_timeout():
    """The load-bearing distinction.

    The cascade catches TimeoutError as "this model timed out". If saturation
    raised TimeoutError, a full local pool would be recorded against a healthy
    model -- and every model after it -- ending the step in
    AllModelsTrippedError: local load reported as every provider being down.
    """
    pool = LLMPool(max_concurrent=1, acquire_timeout=0.05)
    async with pool:
        with pytest.raises(LLMCapacityExhaustedError) as exc:
            async with pool:
                pass
    assert not isinstance(exc.value, TimeoutError)
    assert pool.available == 1


@pytest.mark.asyncio
async def test_a_cancelled_waiter_does_not_leak_a_slot():
    """Phase 1 probes cancel their losing siblings, some of them mid-queue."""
    pool = LLMPool(max_concurrent=1)
    release = asyncio.Event()

    async def holder():
        async with pool:
            await release.wait()

    async def waiter():
        async with pool:
            pass

    h = asyncio.create_task(holder())
    await asyncio.sleep(0)
    w = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    w.cancel()
    release.set()
    await h
    with pytest.raises(asyncio.CancelledError):
        await w

    assert pool.available == 1
    async with pool:  # still usable
        assert pool.available == 0


def test_the_pool_survives_more_than_one_event_loop():
    """A plain asyncio.Semaphore binds to the first loop that waits on it.

    The pool is a process-wide singleton, and this process runs several
    loops -- pytest, and background work calling asyncio.run in threads. The
    second loop to contend a loop-bound semaphore fails with RuntimeError,
    which the cascade would then have charged to a healthy model.
    """
    pool = LLMPool(max_concurrent=1)

    async def contend():
        async def hold():
            async with pool:
                await asyncio.sleep(0.01)

        await asyncio.gather(hold(), hold())  # forces a waiter on this loop

    asyncio.run(contend())
    asyncio.run(contend())  # raised RuntimeError before the per-loop semaphore


def test_a_pool_needs_at_least_one_slot():
    with pytest.raises(ValueError):
        LLMPool(max_concurrent=0)


# ═════════════════════════════════════════════════════════════════════════════
# CascadeExecutor with a pool
# ═════════════════════════════════════════════════════════════════════════════


class _Tools:
    def to_params(self):
        return []


class _SlowLLM:
    def __init__(self, delay: float):
        self._delay = delay
        self.calls = 0

    async def chat(self, **kwargs):
        self.calls += 1
        await asyncio.sleep(self._delay)
        return LLMResponse(content="ok", model=kwargs.get("model", "m"))


def _cascade(llm, pool):
    from weebot.application.agents.executor._cascade import CascadeExecutor

    return CascadeExecutor(llm=llm, tools=_Tools(), agent_role="executor", llm_pool=pool)


@pytest.mark.asyncio
async def test_queue_wait_is_not_charged_against_the_models_timeout():
    """Two calls, one slot, each call takes 0.2s against a 0.3s budget.

    The second call queues ~0.2s for the slot and then needs 0.2s more. With
    the clock and wait_for started before the slot is acquired -- the shape
    this replaced -- that second call spends 0.4s against 0.3s and is recorded
    as the model timing out, although the model answered in 0.2s.
    """
    llm = _SlowLLM(delay=0.2)
    cascade = _cascade(llm, LLMPool(max_concurrent=1))

    results = await asyncio.gather(
        cascade._cascade_try_chat([{"role": "user", "content": "a"}], "model-a", timeout=0.3),
        cascade._cascade_try_chat([{"role": "user", "content": "b"}], "model-b", timeout=0.3),
    )

    assert all(r is not None and r.content == "ok" for r in results), results
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_saturation_propagates_and_is_charged_to_no_model():
    llm = _SlowLLM(delay=0.0)
    pool = LLMPool(max_concurrent=1, acquire_timeout=0.05)
    cascade = _cascade(llm, pool)

    async with pool:  # someone else holds the only slot
        with pytest.raises(LLMCapacityExhaustedError):
            await cascade._cascade_try_chat([{"role": "user", "content": "x"}], "model-a")

    assert llm.calls == 0, "the model was called without a slot"
    assert not cascade.cascade_is_tripped("model-a")
    recorded = [d for d in cascade._tracker.recent(500) if d.model_name == "model-a"]
    assert recorded == [], f"saturation was recorded against the model: {recorded}"


@pytest.mark.asyncio
async def test_a_tripped_model_does_not_queue_for_a_slot():
    llm = _SlowLLM(delay=0.0)
    pool = LLMPool(max_concurrent=1, acquire_timeout=0.05)
    cascade = _cascade(llm, pool)
    for _ in range(10):
        cascade._cascade_record_failure("model-a")
    assert cascade.cascade_is_tripped("model-a")

    async with pool:  # pool full; a tripped model must not wait for it
        assert await cascade._cascade_try_chat([], "model-a") is None


# ═════════════════════════════════════════════════════════════════════════════
# Wiring -- the level beyond the DI census
# ═════════════════════════════════════════════════════════════════════════════


# Building the container imports the whole application, including the browser
# stack -- 20-30s on a cold Windows run, past the suite's 60s per-test default
# once configure_defaults runs on top. Build it once for the module, and give
# the two tests that need it the headroom other container tests take.
@pytest.fixture(scope="module")
def container():
    from weebot.application.di import Container

    c = Container()
    c.configure_defaults()
    return c


@pytest.mark.timeout(180)
def test_the_executor_that_runs_steps_holds_the_containers_pool(container):
    """The census proves `llm_pool` is RESOLVED. This proves where it lands.

    ExecutingState runs every step through the mediator, and the executor the
    mediator's ExecuteStepHandler builds comes from the container's
    `_executor_factory`. The remediation plan named a different site -- the
    executor PlanActFlow constructs itself, which only serves the summarize
    fallback. Wiring that one would have satisfied the census and bounded
    nothing: the census cannot tell the two apart. This can.
    """
    from weebot.application.cqrs.commands import ExecuteStepCommand
    from weebot.application.cqrs.mediator import Mediator

    handler = container.get(Mediator)._command_handlers[ExecuteStepCommand]
    factory = getattr(handler, "_executor_factory", None)
    assert factory is not None, "ExecuteStepHandler has no executor factory to inspect"

    executor = factory(model="test-model", session=None)

    pool = container.get("llm_pool")
    assert isinstance(pool, LLMPool)
    assert executor._cascade._llm_pool is pool


# ═════════════════════════════════════════════════════════════════════════════
# TaskRunner
# ═════════════════════════════════════════════════════════════════════════════


class _TrackedFlow:
    """A flow that records how many flows are running when it runs."""

    running = 0
    peak = 0

    def __init__(self, gate: asyncio.Event | None = None, fail: bool = False):
        self._gate = gate
        self._fail = fail
        self._session = None

    async def run(self, prompt: str):
        cls = type(self)
        cls.running += 1
        cls.peak = max(cls.peak, cls.running)
        try:
            if self._gate is not None:
                await self._gate.wait()
            else:
                await asyncio.sleep(0.01)
            if self._fail:
                raise RuntimeError("flow failed")
        finally:
            cls.running -= 1
        return
        yield  # pragma: no cover -- makes this an async generator

    def is_done(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass


def _runner(max_concurrent_flows: int, max_session_retries: int = 3):
    from weebot.application.services.task_runner import TaskRunner
    from weebot.domain.models.session import Session

    sessions: dict[str, Session] = {}

    async def load(session_id):
        return sessions.get(session_id)

    async def save(session):
        sessions[session.id] = session

    repo = AsyncMock()
    repo.load_session = AsyncMock(side_effect=load)
    repo.save_session = AsyncMock(side_effect=save)
    runner = TaskRunner(
        state_repo=repo,
        max_concurrent_flows=max_concurrent_flows,
        max_session_retries=max_session_retries,
    )
    return runner, sessions


@pytest.mark.asyncio
async def test_running_flows_never_exceed_the_bound():
    """Before this, start_session spawned every flow at once, with no ceiling."""
    from weebot.domain.models.session import Session

    _TrackedFlow.running = _TrackedFlow.peak = 0
    runner, _ = _runner(max_concurrent_flows=2)

    for i in range(7):
        await runner.start_session(
            Session(id=f"s{i}", user_id="u", agent_id="a"), lambda s: _TrackedFlow()
        )
    await asyncio.gather(*list(runner._tasks.values()))

    assert _TrackedFlow.peak == 2, f"peak running flows {_TrackedFlow.peak}, bound 2"


@pytest.mark.asyncio
async def test_a_retry_at_capacity_does_not_deadlock(monkeypatch):
    """_run_flow's retry calls _start_direct from INSIDE a running flow.

    With the slot taken when the task is created, the retry would wait for a
    slot its own caller holds, at a bound of 1 forever. The slot is acquired
    inside the task, so the failing flow releases it before the retry runs.
    """
    import weebot.application.services.task_runner as tr
    from weebot.domain.models.session import Session

    real_sleep = asyncio.sleep
    monkeypatch.setattr(tr.asyncio, "sleep", lambda s, *a, **k: real_sleep(0))

    _TrackedFlow.running = _TrackedFlow.peak = 0
    runner, sessions = _runner(max_concurrent_flows=1, max_session_retries=1)
    attempts = []

    def factory(session):
        attempts.append(session.id)
        return _TrackedFlow(fail=len(attempts) == 1)  # first attempt fails

    await runner.start_session(Session(id="r1", user_id="u", agent_id="a"), factory)

    async def drain():
        # Yield on every pass. Awaiting gather() over tasks that are already
        # done never yields to the loop, so the tasks' done-callbacks -- which
        # are what remove them from `_tasks` -- would never get to run.
        while runner._tasks:
            await asyncio.gather(*list(runner._tasks.values()), return_exceptions=True)
            await real_sleep(0.01)

    await asyncio.wait_for(drain(), timeout=5.0)

    assert len(attempts) == 2, f"expected one retry, saw {len(attempts)} attempts"
    assert _TrackedFlow.peak == 1


@pytest.mark.timeout(180)
def test_the_container_builds_the_task_runner_with_the_setting(container):
    from weebot.application.services.task_runner import TaskRunner
    from weebot.config.settings import WeebotSettings

    runner = container.get(TaskRunner)
    assert runner.max_concurrent_flows == WeebotSettings().max_concurrent_flows


def test_a_runner_needs_at_least_one_flow_slot():
    with pytest.raises(ValueError):
        _runner(max_concurrent_flows=0)
