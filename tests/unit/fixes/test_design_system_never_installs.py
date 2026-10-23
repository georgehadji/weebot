"""design_system does not install global npm packages on its own (F51).

When skillui failed with "not found" it ran `npm install -g skillui`: a global
change to the machine, made by the agent without asking. Now it says how to
install and stops.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from weebot.tools.design_system_tool import DesignSystemTool


async def test_a_missing_skillui_is_reported_not_installed():
    calls = []

    def _run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="skillui: not found")

    with patch("subprocess.run", side_effect=_run):
        result = await DesignSystemTool().execute(url="https://example.com")
    assert result.is_error and "npm install -g skillui" in (result.error or "")
    assert not any(c[:2] == ["npm", "install"] for c in calls)
