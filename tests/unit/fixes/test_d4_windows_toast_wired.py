"""D4: desktop toasts are subscribed at the web root, behind WEEBOT_WINDOWS_TOAST.

`WindowsToastSubscriber` had no caller, so the only toast path never ran. A toast
shows error text on screen, so the text is redacted first: an error that quotes a
key must not put the key on the desktop.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from weebot.domain.models.event import ErrorEvent
from weebot.interfaces.windows_toast_subscriber import WindowsToastSubscriber

_KEY = "sk-or-v1-" + "a" * 48


async def test_a_toast_never_shows_a_key():
    channel = SimpleNamespace(send=AsyncMock())
    await WindowsToastSubscriber(channel=channel).on_event(ErrorEvent(error=f"bad key {_KEY}"))
    shown = channel.send.await_args.args[0].message
    assert _KEY not in shown and "REDACTED" in shown


def test_toasts_subscribe_only_when_the_flag_is_on(monkeypatch):
    import weebot.config.feature_flags as flags
    from weebot.interfaces import windows_toast_subscriber as module

    bus = MagicMock()
    monkeypatch.delenv("WEEBOT_WINDOWS_TOAST", raising=False)
    importlib.reload(flags)
    assert module.subscribe_if_enabled(bus) is None
    bus.subscribe.assert_not_called()

    monkeypatch.setenv("WEEBOT_WINDOWS_TOAST", "1")
    importlib.reload(flags)
    try:
        sub = module.subscribe_if_enabled(bus)
        bus.subscribe.assert_called_once_with(sub.on_event)
    finally:
        monkeypatch.delenv("WEEBOT_WINDOWS_TOAST")
        importlib.reload(flags)


def test_the_web_root_calls_it():
    from pathlib import Path

    src = Path("weebot/interfaces/web/main.py").read_text(encoding="utf-8")
    assert "subscribe_if_enabled(event_bus)" in src
