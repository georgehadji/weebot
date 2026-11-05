"""Which gateway adapters exist and which of them a process runs (H28).

The built-ins are listed by ``module:Class`` and imported only when asked for, so a process
that uses Telegram does not import the Slack client. Third-party adapters register through
the ``weebot.gateways`` entry-point group (``name = package.module:Class``); a broken one is
logged and skipped.

``start_configured`` builds every long-running adapter whose settings are present and starts it;
webhook adapters are not built here (their routers build them per request).
"""

from __future__ import annotations

import importlib
import logging
from importlib import metadata
from typing import Any

from weebot.interfaces.gateways.base import GatewayAdapter

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "weebot.gateways"

_BUILT_IN = {
    "telegram": "weebot.interfaces.gateways.telegram:TelegramAdapter",
    "discord": "weebot.interfaces.gateways.discord:DiscordAdapter",
    "slack": "weebot.interfaces.gateways.slack:SlackAdapter",
    "whatsapp": "weebot.interfaces.gateways.whatsapp:WhatsAppAdapter",
    "signal": "weebot.interfaces.gateways.signal:SignalAdapter",
    "email": "weebot.interfaces.gateways.email:EmailAdapter",
}


def _load(target: str) -> type[GatewayAdapter]:
    module, _, attr = target.partition(":")
    cls = getattr(importlib.import_module(module), attr)
    if not (isinstance(cls, type) and issubclass(cls, GatewayAdapter)):
        raise TypeError(f"{target} is not a GatewayAdapter")
    return cls


class GatewayRegistry:
    def __init__(self, extra: dict[str, str] | None = None) -> None:
        self._targets = {**_BUILT_IN, **(extra or {})}
        self._classes: dict[str, type[GatewayAdapter]] = {}

    def discover(self) -> None:
        """Add the adapters installed packages declare under ``weebot.gateways``."""
        for entry in metadata.entry_points(group=ENTRY_POINT_GROUP):
            if entry.name in _BUILT_IN:
                logger.warning("gateway entry point %r shadows a built-in; ignored", entry.name)
                continue
            self._targets[entry.name] = entry.value

    def names(self) -> list[str]:
        return sorted(self._targets)

    def get(self, name: str) -> type[GatewayAdapter] | None:
        if name not in self._classes:
            target = self._targets.get(name)
            if target is None:
                return None
            try:
                self._classes[name] = _load(target)
            except Exception as exc:
                logger.warning("gateway %r could not be loaded: %s", name, exc)
                return None
        return self._classes[name]

    async def start_configured(self, settings: Any, container: Any) -> dict[str, GatewayAdapter]:
        """Build and start every adapter whose settings are present.

        One adapter failing to start never blocks the others.
        """
        running: dict[str, GatewayAdapter] = {}
        for name in self.names():
            cls = self.get(name)
            if cls is None or not cls.configured(settings):
                continue
            try:
                adapter = cls.build(settings, container)
                if adapter is None:
                    continue
                await adapter.start()
            except Exception as exc:
                logger.warning("%s gateway failed to start: %s", name, exc)
                continue
            running[name] = adapter
            logger.info("%s gateway started", name)
        if not running:
            logger.info("No polling gateway configured")
        return running


async def stop_all(adapters: dict[str, GatewayAdapter]) -> None:
    for name, adapter in adapters.items():
        try:
            await adapter.stop()
        except Exception as exc:
            logger.warning("%s gateway did not stop cleanly: %s", name, exc)
