"""computer_use refuses to type when it cannot confirm the window it was told to (F75).

With `require_window` set, a failing pygetwindow import or call was swallowed
("advisory") and the keystrokes went to whatever window had focus.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from weebot.tools import computer_use


async def test_typing_is_refused_when_the_focus_check_cannot_run():
    fake_gui = MagicMock()
    with patch.dict(sys.modules, {"pygetwindow": None}), patch.object(
        computer_use, "pyautogui", fake_gui, create=True
    ):
        result = await computer_use.ComputerUseTool().execute(
            action="type", text="secret", require_window="Notepad"
        )
    assert result.is_error and "Notepad" in (result.error or "")
    fake_gui.write.assert_not_called()
    fake_gui.typewrite.assert_not_called()
