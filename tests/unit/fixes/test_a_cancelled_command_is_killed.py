"""Cancelling a run kills the command it was waiting on.

Found by review of the thread fallback: a cancelled ``execute`` left the process running
until its timeout, on the thread fallback (``asyncio.to_thread`` cannot be cancelled)
and on the normal path (nothing killed the process on ``CancelledError``).
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

psutil = pytest.importorskip("psutil")

_SLEEPER = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)"


async def _pid(pid_file):
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            return int(pid_file.read_text())
        await asyncio.sleep(0.1)
    raise AssertionError("the command never started")


@pytest.mark.parametrize("thread_fallback", [False, True])
async def test_a_cancelled_execute_kills_its_process(monkeypatch, tmp_path, thread_fallback):
    if thread_fallback:
        async def refuse(*_a, **_k):
            raise NotImplementedError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    pid_file = tmp_path / "sleeper.pid"
    task = asyncio.create_task(
        NativeWindowsSandbox(SandboxConfig()).execute(
            [sys.executable, "-c", _SLEEPER, str(pid_file)], timeout=30
        )
    )
    pid = await _pid(pid_file)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        psutil.Process(pid).wait(timeout=5)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired:
        psutil.Process(pid).kill()
        raise AssertionError("the cancelled command was still running") from None
