"""Firing an alert must not depend on which thread you are on.

`AlertManager` guards every mutation with an RLock and its docstring says
"Thread-safe for concurrent access." `_dispatch` broke that promise: it began
with `loop = asyncio.get_event_loop()` -- a variable it then never used -- and
that call raises RuntimeError in any thread without a running loop. Measured
before the fix:

    from the loop thread    -> ok, 1 async handler delivered
    from a foreign thread   -> RuntimeError: There is no current event loop in
                               thread 'Thread-worker'.  0 delivered
    from a plain script     -> RuntimeError: There is no current event loop in
                               thread 'MainThread'.     0 delivered

So an alert fired from a worker thread raised out of `fire_alert`, while
holding the lock, after the synchronous handlers had already run -- a partial
dispatch and an exception, from a dead assignment. `asyncio.ensure_future` was
the second half of it: not thread-safe, and the task it returns was dropped, so
a failing async handler was never heard from.

This is the same defect as D51 in behavior_router, in a different module, and
it was hidden behind a third one: until `asyncio.coroutine` was removed from
line 105, this module could not be imported at all.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from weebot.core import alerting as al


def _manager():
    m = al.AlertManager()
    delivered: list[al.Alert] = []

    async def async_handler(alert):
        delivered.append(alert)

    def sync_handler(alert):
        pass

    m.register_handler(sync_handler)
    m.register_async_handler(async_handler)
    return m, delivered


def _alert(name: str = "a"):
    return al.Alert(name=name, severity=al.AlertSeverity.WARNING, message="m")


@pytest.mark.asyncio
async def test_an_alert_fired_from_a_worker_thread_reaches_async_handlers():
    m, delivered = _manager()
    m.bind_loop()

    errors: list[str] = []
    done = threading.Event()

    def worker():
        try:
            m.fire_alert(_alert("from-thread"))
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            done.set()

    threading.Thread(target=worker, name="Thread-worker").start()
    await asyncio.get_running_loop().run_in_executor(None, done.wait)
    assert errors == [], errors

    for _ in range(40):
        if delivered:
            break
        await asyncio.sleep(0.05)
    assert [a.name for a in delivered] == ["from-thread"]


@pytest.mark.asyncio
async def test_firing_from_the_loop_thread_still_works():
    """The control: the one context that used to work must keep working."""
    m, delivered = _manager()
    m.fire_alert(_alert("from-loop"))
    for _ in range(40):
        if delivered:
            break
        await asyncio.sleep(0.05)
    assert [a.name for a in delivered] == ["from-loop"]


def test_firing_with_no_loop_at_all_does_not_raise(caplog):
    """A plain synchronous script has no loop. It must still get its alert.

    Fired from a fresh thread for the same reason as above: the main thread may
    carry a set-but-not-running loop left by an earlier async test.
    """
    m, delivered = _manager()
    errors: list[str] = []

    def worker():
        try:
            m.fire_alert(_alert("no-loop"))
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    with caplog.at_level("ERROR", logger=al.__name__):
        t = threading.Thread(target=worker, name="Thread-no-loop")
        t.start()
        t.join()
    assert errors == [], errors
    assert m.get_alert("no-loop") is not None, "the alert itself was lost"
    assert delivered == []
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "no-loop" in text or "async" in text.lower(), (
        f"async handlers were skipped with no record of it: {text!r}"
    )


def test_synchronous_handlers_run_with_no_loop():
    """They never needed a loop, and used to be reached only by luck of ordering.

    Run in a fresh thread deliberately. Called on the main thread this passed
    even before the fix, because an earlier async test leaves a loop SET (not
    running) there and `get_event_loop` returned it -- the test would have been
    green for a reason that has nothing to do with the code. A brand-new thread
    has no loop of any kind, which is the state a plain script is really in.
    """
    m = al.AlertManager()
    seen = []
    m.register_handler(lambda alert: seen.append(alert.name))

    async def never_runs(alert):
        pass

    m.register_async_handler(never_runs)

    errors: list[str] = []

    def worker():
        try:
            m.fire_alert(_alert("sync-only"))
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    t = threading.Thread(target=worker, name="Thread-no-loop")
    t.start()
    t.join()
    assert errors == [], errors
    assert seen == ["sync-only"]


@pytest.mark.asyncio
async def test_a_failing_async_handler_is_reported_not_dropped(caplog):
    m = al.AlertManager()
    m.bind_loop()

    async def boom(alert):
        raise RuntimeError("handler exploded")

    m.register_async_handler(boom)
    with caplog.at_level("ERROR", logger=al.__name__):
        m.fire_alert(_alert("boom"))
        for _ in range(40):
            if any("exploded" in r.getMessage() for r in caplog.records):
                break
            await asyncio.sleep(0.05)
    assert any("exploded" in r.getMessage() for r in caplog.records), (
        "the task was dropped, so its exception was never retrieved"
    )


@pytest.mark.asyncio
async def test_resolving_an_alert_dispatches_too():
    m, delivered = _manager()
    m.bind_loop()
    m.fire_alert(_alert("r"))
    assert m.resolve_alert("r") is True
    for _ in range(40):
        if len(delivered) >= 2:
            break
        await asyncio.sleep(0.05)
    assert len(delivered) == 2, f"resolve did not dispatch: {len(delivered)}"
