"""The web backend can start processes on Windows, and a spawn failure says why.

Found on live session de5d0990 ("tidy up my Downloads folder"): every powershell and
bash call returned ``ERROR: Failed to start process: `` with nothing after it. The
backend ran ``uvicorn.run(..., reload=True)``; with reload, uvicorn 0.51 builds a
``SelectorEventLoop`` on Windows, where ``asyncio.create_subprocess_exec`` raises a
``NotImplementedError`` whose message is empty.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
import uvicorn

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox


@pytest.mark.skipif(sys.platform != "win32", reason="the selector loop is a Windows problem")
def test_the_reloading_backend_loop_can_start_a_process():
    from weebot.interfaces.web.main import uvicorn_loop

    config = uvicorn.Config("weebot.interfaces.web.main:app", loop=uvicorn_loop(), reload=True)
    factory = config.get_loop_factory()

    async def spawn() -> int:
        proc = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        return await proc.wait()

    assert asyncio.run(spawn(), loop_factory=factory) == 0


def test_linux_and_mac_keep_uvicorns_own_loop_choice(monkeypatch):
    from weebot.interfaces.web.main import uvicorn_loop

    monkeypatch.setattr(sys, "platform", "linux")
    assert uvicorn_loop() == "auto"


async def test_a_spawn_failure_names_the_exception(monkeypatch):
    # An exception with an empty message must still say what went wrong.
    async def refuse(*_a, **_k):
        raise PermissionError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)
    result = await NativeWindowsSandbox(SandboxConfig()).execute([sys.executable, "-c", "pass"])
    assert result.stderr == "Failed to start process: PermissionError"
