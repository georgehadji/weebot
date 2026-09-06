"""Teardown for child processes, in one place.

This module exists because the knowledge did not travel. `latex_compiler`
already learned — the hard way, and wrote it down — that `proc.kill()` reaches
only the direct child and that a post-kill `communicate()` blocks forever on a
pipe an orphaned grandchild still holds. Two hundred lines away,
`qmd_integration/mcp_client.py` called `terminate()` with no `wait()` at all
and left a defunct entry per cycle, and assigned a second child to a local so
nothing could reach it.

One rule written twice drifts; one rule written once and imported does not.
"""

from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# Long enough for a cooperative child to flush and exit, short enough that
# shutdown does not appear to hang.
DEFAULT_REAP_TIMEOUT_S = 5.0


def reap_process(
    proc: subprocess.Popen | None,
    *,
    timeout: float = DEFAULT_REAP_TIMEOUT_S,
) -> int | None:
    """Stop *proc* and collect its exit status. Returns the code, or None.

    ``terminate()`` on its own is not enough, and the difference is visible:

        after terminate() with no wait():   Z    sleep
        after wait():                       (gone)

    A terminated child stays in state ``Z`` — defunct, holding a PID — until
    the parent reaps it. In a long-lived agent process that is one leaked
    entry per start/stop cycle.

    Escalates to ``kill()`` if the child does not honour SIGTERM within
    *timeout*, closes the pipes so no descriptor is left behind, and never
    raises: teardown that throws leaves the *rest* of the teardown undone,
    which is how a single stuck child strands a browser and a temp directory
    with it.
    """
    if proc is None:
        return None

    if proc.poll() is None:
        try:
            proc.terminate()
        except (ProcessLookupError, OSError):
            logger.debug("Process %s was already gone at terminate().", proc.pid, exc_info=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Process %s ignored SIGTERM after %.1fs; killing it.", proc.pid, timeout
            )
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                logger.debug("Process %s exited between wait() and kill().", proc.pid, exc_info=True)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.error("Process %s survived SIGKILL; leaving it.", proc.pid)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Reaping process %s failed.", proc.pid, exc_info=True)

    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is not None and not stream.closed:
            try:
                stream.close()
            except Exception:
                logger.debug("Closing a pipe of process %s failed.", proc.pid, exc_info=True)

    return proc.returncode


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill *proc* and every descendant it spawned.

    ``proc.kill()`` alone only terminates the direct child (e.g. latexmk);
    grandchildren (xelatex, biber, pygmentize) survive, keep the stdout/stderr
    pipes open, and a post-kill ``communicate()`` blocks forever waiting for
    EOF on a pipe an orphan still holds.

    Requires the child to have been started in its own process group
    (``start_new_session=True`` or ``preexec_fn=os.setsid``) on POSIX;
    otherwise ``getpgid`` returns the *caller's* group and the signal would
    come home.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        return

    import signal

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
