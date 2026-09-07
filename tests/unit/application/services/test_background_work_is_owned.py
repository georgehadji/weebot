"""Fire-and-forget work needs an owner, or it is neither run nor observed.

P3-4. `flows/states/completed.py` spawned three post-completion jobs — the
retention review, skill-gap processing and the dream scan — with bare
`asyncio.ensure_future(...)` and dropped every handle. `cli/agent_runner.py`
had a fourth of the same shape.

Measured on a CLI-shaped process (`asyncio.run(body())`, body returns):

- Both orphans were CANCELLED at loop teardown, including one that needed 10ms.
  So in the CLI this work never completed at all, after paying to construct a
  `Container()` and start live LLM adapters inside each coroutine.
- An orphan that raised produced "Task exception was never retrieved" from the
  event loop's default handler on stderr, bypassing the application's logging.
- The documented garbage-collection hazard (the loop keeps only a weak
  reference) did not reproduce in a short probe, so it is a reason to hold a
  reference, not a measured failure.

`spawn()` answers the last two; only `drain()` answers the first, and only
because `cli/commands/flow.py::_run_async` calls it.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from weebot.application.services.background_tasks import (
    BackgroundTasks,
    get_background_tasks,
)


@pytest.mark.asyncio
async def test_a_spawned_task_is_held_until_it_finishes():
    bg = BackgroundTasks()
    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.sleep(0.01)
        return "done"

    task = bg.spawn(work(), name="unit")
    await started.wait()
    assert bg.pending == 1, "the owner dropped its reference while the task was in flight"
    assert await task == "done"
    await asyncio.sleep(0)
    assert bg.pending == 0, "the owner never released the finished task"


@pytest.mark.asyncio
async def test_a_failure_reaches_the_application_logger(caplog):
    bg = BackgroundTasks()

    async def boom():
        raise RuntimeError("retention review blew up")

    with caplog.at_level(logging.WARNING):
        task = bg.spawn(boom(), name="retention-review:abcd1234")
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)

    records = [r for r in caplog.records if "retention review blew up" in r.getMessage()]
    assert records, (
        "the failure was left for the event loop's default handler to print to "
        "stderr at some later garbage collection"
    )
    assert "retention-review:abcd1234" in records[0].getMessage(), "which task failed is unnamed"


@pytest.mark.asyncio
async def test_drain_lets_short_work_finish():
    bg = BackgroundTasks()
    finished = []

    async def quick():
        await asyncio.sleep(0.01)
        finished.append("quick")

    bg.spawn(quick(), name="quick")
    done, abandoned = await bg.drain(timeout=2.0)

    assert finished == ["quick"], "work well inside the bound was still cut off"
    assert (done, abandoned) == (1, 0)


@pytest.mark.asyncio
async def test_drain_is_bounded_and_says_what_it_abandoned(caplog):
    """A shutdown that waits indefinitely on background work is a hang."""
    bg = BackgroundTasks()

    async def slow():
        await asyncio.sleep(30)

    bg.spawn(slow(), name="dream-scan")
    loop = asyncio.get_running_loop()
    started = loop.time()
    with caplog.at_level(logging.INFO):
        done, abandoned = await bg.drain(timeout=0.1)
    elapsed = loop.time() - started

    assert elapsed < 5.0, f"drain waited {elapsed:.1f}s on a 0.1s bound"
    assert (done, abandoned) == (0, 1)
    assert any("dream-scan" in r.getMessage() for r in caplog.records), (
        "abandoning a task silently is how the original orphans hid"
    )
    assert bg.pending == 0


@pytest.mark.asyncio
async def test_drain_on_an_idle_owner_is_a_no_op():
    assert await BackgroundTasks().drain(timeout=0.1) == (0, 0)


def test_the_cli_wrapper_drains_before_closing_the_pools():
    """Order matters: the background jobs read the database."""
    import inspect

    import cli.commands.flow as flow_cmd

    src = inspect.getsource(flow_cmd._run_async)
    assert "drain()" in src, "the CLI wrapper does not drain; spawned work is still cancelled"
    assert src.index("drain()") < src.index("close_all_pools()"), (
        "pools are torn down before the background work that reads them"
    )


def test_the_default_owner_is_stable():
    assert get_background_tasks() is get_background_tasks()


def test_completed_state_spawns_through_the_owner():
    """The three sites the record names."""
    import inspect

    from weebot.application.flows.states import completed

    src = inspect.getsource(completed)
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "ensure_future(" not in code, "an orphaned spawn is still present in CompletedState"
    assert code.count("_background().spawn(") == 3
