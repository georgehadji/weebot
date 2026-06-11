"""Windows desktop companion — system tray, global hotkey, and quick-prompt overlay.

Usage:
    python -m weebot.interfaces.windows
or:
    weebot companion
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_companion(adapter: Optional[object] = None) -> None:
    """Start the full desktop companion (tray + hotkey + overlay).

    This is the main entry point called by ``weebot companion``.
    Blocks until the user quits from the tray menu.
    """
    if adapter is None:
        from weebot.infrastructure.adapters.windows_desktop import WindowsDesktopAdapter
        adapter = WindowsDesktopAdapter()
    await adapter.start()

    logger.info("weebot companion running — quit from system tray")

    # Keep alive until stop is triggered
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await adapter.stop()


def main() -> None:
    """Entry point for ``python -m weebot.interfaces.windows``."""
    asyncio.run(run_companion())


if __name__ == "__main__":
    main()
