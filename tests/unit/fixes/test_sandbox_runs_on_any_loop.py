"""The Windows sandbox starts processes even on an event loop that cannot spawn them.

Found by review of the de5d0990 fix: the Proactor loop was chosen only in
``main.py``'s ``__main__`` block, so ``uvicorn weebot.interfaces.web.main:app --reload``
on Windows still built a SelectorEventLoop and every shell tool failed with
NotImplementedError. The sandbox now runs the process from a worker thread instead.
"""

from __future__ import annotations

import asyncio
import sys

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

_PRINT = [sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"]


def _refuse_subprocesses(monkeypatch):
    async def refuse(*_a, **_k):
        raise NotImplementedError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)


async def test_a_loop_without_subprocess_support_still_runs_the_command(monkeypatch):
    _refuse_subprocesses(monkeypatch)
    result = await NativeWindowsSandbox(SandboxConfig()).execute(_PRINT)
    assert result.stdout.strip() == "hi"
    assert result.returncode == 3


async def test_the_thread_fallback_keeps_the_timeout(monkeypatch):
    _refuse_subprocesses(monkeypatch)
    sleep = [sys.executable, "-c", "import time; time.sleep(30)"]
    result = await NativeWindowsSandbox(SandboxConfig()).execute(sleep, timeout=1)
    assert result.timed_out and result.returncode == -1


def test_a_selector_loop_runs_the_command():
    async def run():
        return await NativeWindowsSandbox(SandboxConfig()).execute(_PRINT)

    result = asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    assert result.stdout.strip() == "hi"
