"""D4: sandbox output goes through `safe_decode`, so Windows code pages survive.

The sandboxes decoded with `utf-8, errors="replace"`, so CP-1252 output from
PowerShell (an accented letter, a section sign) came back as U+FFFD.
`platform_encoding.safe_decode` existed for exactly this and had no caller.
"""

import asyncio
import sys

import pytest

from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
from weebot.infrastructure.sandbox.wsl2 import WSL2Sandbox

_CP1252 = b"caf\xe9 \xa7"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows sandbox")
async def test_native_sandbox_keeps_cp1252_output():
    emit = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({_CP1252!r})"]
    result = await NativeWindowsSandbox(SandboxConfig()).execute(emit)
    assert result.stdout == "café §"


async def test_wsl2_sandbox_keeps_cp1252_output(monkeypatch):
    class _Proc:
        returncode = 0

        async def communicate(self):
            return _CP1252, b""

    async def spawn(*_a, **_k):
        return _Proc()

    async def available(self):
        return True

    monkeypatch.setattr(WSL2Sandbox, "is_available", available)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = await WSL2Sandbox(SandboxConfig()).execute(["echo"])
    assert result.stdout == "café §"
