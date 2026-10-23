"""PowerShell output reaches the agent as UTF-8.

Seen in the 2026-10-23 agent-uses batch: a weather line came back as
"12A�C" instead of "12°C". Windows PowerShell 5.1 writes piped output in
the console code page, while the sandbox decodes UTF-8, so every non-ASCII
character was mangled and the agent "fixed" its file by dropping them.
"""

from __future__ import annotations

import sys

import pytest

from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")


@pytest.mark.asyncio
async def test_non_ascii_output_survives():
    result = await NativeWindowsSandbox().execute_shell(
        "Write-Output ('12' + [char]0x00B0 + 'C, ' + [char]0x03B1)", shell="powershell", timeout=30
    )
    assert "12°C, α" in result.stdout, repr(result.stdout)
