"""Whether the running code is inside a cron agent job.

The schedule tool refuses to schedule from inside a cron job, so a job cannot
schedule itself into an infinite loop. The flag that told it so used to be an
environment variable: ``CronAgentRunner.run`` set ``WEEBOT_CRON_CONTEXT=1``
in the process environment and never unset it.

That is process-wide, and the scheduler runs cron jobs inside the web server's
own process. After the first scheduled job ran, scheduling would have been
disabled for every user's session until the server restarted. It never
happened only because every cron job failed earlier, on a DI ``KeyError``,
before ``run`` was called -- fixing that is what would have switched it on.
It surfaced as eight ScheduleTool tests failing in CI after a cron test ran in
the same process.

A ``ContextVar`` scopes the flag to the cron job's own task: it follows every
``await`` and every task the job creates, and nothing else. Nothing reads the
flag from a subprocess, which is the only thing an environment variable would
have been needed for.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_in_cron_job: ContextVar[bool] = ContextVar("weebot_in_cron_job", default=False)


def in_cron_job() -> bool:
    """True while the calling code runs inside a cron agent job."""
    return _in_cron_job.get()


@contextmanager
def cron_job_context() -> Iterator[None]:
    """Mark everything run within this block as part of a cron job."""
    token = _in_cron_job.set(True)
    try:
        yield
    finally:
        _in_cron_job.reset(token)
