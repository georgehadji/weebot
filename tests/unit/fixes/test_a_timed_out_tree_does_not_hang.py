"""A timed-out command returns even when a process it started still holds the output.

Found by review of the thread fallback: after killing a timed-out process it called
``communicate()``, which reads the pipes to the end. On Windows ``kill()`` ends only the
direct child, so a grandchild that inherited stdout kept the pipe open and the call,
and the agent's step, never returned.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

# The parent starts a grandchild on its own stdout, records the grandchild's pid,
# then sleeps past the timeout.
_PARENT = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'],"
    " stdout=sys.stdout)\n"
    "open(sys.argv[1], 'w').write(str(p.pid))\n"
    "time.sleep(60)\n"
)


def _refuse_subprocesses(monkeypatch):
    async def refuse(*_a, **_k):
        raise NotImplementedError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)


@pytest.mark.skipif(sys.platform != "win32", reason="kill() ends the whole tree only off Windows")
async def test_the_thread_fallback_returns_on_timeout_with_a_grandchild(monkeypatch, tmp_path):
    _refuse_subprocesses(monkeypatch)
    pid_file = tmp_path / "grandchild.pid"
    command = [sys.executable, "-c", _PARENT, str(pid_file)]
    try:
        result = await asyncio.wait_for(
            NativeWindowsSandbox(SandboxConfig()).execute(command, timeout=2), timeout=12
        )
        assert result.timed_out
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 9)
            except OSError:
                pass
