"""An owner for fire-and-forget work, so it is neither lost nor unobserved.

`asyncio.ensure_future(coro)` with the result dropped on the floor is not a
background task; it is a wish. Three things go wrong, and all three were
measured against the spawns in `flows/states/completed.py`:

1. **In a short-lived process it never runs.** `asyncio.run()` cancels whatever
   is still pending when the main coroutine returns. Measured: two orphans
   spawned from a flow that then returned were both cancelled at teardown —
   including one that needed 10ms. Every CLI invocation therefore paid to build
   a `Container()` and start LLM adapters for work that was then thrown away.

2. **Failures bypass the application's logging.** An orphan that raises produces
   "Task exception was never retrieved" on stderr from the event loop's default
   handler, whenever the garbage collector gets to it. Measured.

3. **The task can be collected mid-flight.** The loop keeps only a weak
   reference, which is why CPython's own documentation says to keep a strong
   one. This did not reproduce in a short probe — a task pending on a sleep
   survived an explicit `gc.collect()` — so it is a documented hazard here
   rather than a measured one.

`spawn()` fixes (2) and (3). Only `drain()` fixes (1), and only if a caller
actually calls it: see `cli/commands/flow.py::_run_async`, which drains before
tearing down the connection pools the background work needs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DRAIN_TIMEOUT_S = 10.0


class BackgroundTasks:
    """Holds, observes and drains fire-and-forget work."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
        """Start ``coro`` and keep a strong reference to it until it finishes."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        return task

    def _finished(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # Retrieve it here, through this application's logger, rather than
            # leaving the loop's default handler to print it to stderr at some
            # later garbage collection.
            logger.warning("Background task %s failed: %s", task.get_name(), exc, exc_info=exc)

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def drain(self, timeout: float = DEFAULT_DRAIN_TIMEOUT_S) -> tuple[int, int]:
        """Give outstanding work a bounded chance to finish.

        Returns ``(finished, abandoned)``. Whatever the bound does not cover is
        cancelled and reported, because a shutdown that waits indefinitely on
        background work is a hang, not a courtesy.
        """
        outstanding = list(self._tasks)
        if not outstanding:
            return (0, 0)

        logger.debug("Draining %d background task(s), up to %.1fs", len(outstanding), timeout)
        done, pending = await asyncio.wait(outstanding, timeout=timeout)

        for task in pending:
            task.cancel()
        if pending:
            # Let the cancellations actually land before the loop closes,
            # otherwise they surface as "Task was destroyed but it is pending!".
            await asyncio.gather(*pending, return_exceptions=True)
            logger.info(
                "Abandoned %d background task(s) after %.1fs: %s",
                len(pending),
                timeout,
                ", ".join(sorted(t.get_name() for t in pending)),
            )
        return (len(done), len(pending))


_default: BackgroundTasks | None = None


def get_background_tasks() -> BackgroundTasks:
    """The process-wide owner, for callers with nowhere to hang one."""
    global _default
    if _default is None:
        _default = BackgroundTasks()
    return _default
