"""BaseNotificationAdapter — base class for notification adapters using aiohttp.

Provides lifecycle-managed ``aiohttp.ClientSession`` creation and teardown.
Notification adapters (Telegram, Discord, Slack, etc.) should inherit from
this to avoid leaking HTTP connections.

Usage::

    class TelegramNotificationAdapter(BaseNotificationAdapter, NotificationPort):
        async def notify(self, notification: Notification) -> NotificationResult:
            client = self._get_http_client()
            async with client.post(url, json=payload) as resp:
                ...
        # close() and __aexit__ are inherited
"""
from __future__ import annotations

from typing import Any, Optional


try:
    import aiohttp as _aiohttp
    HAS_AIOHTTP = True
except ImportError:
    _aiohttp = None
    HAS_AIOHTTP = False


class BaseNotificationAdapter:
    """Base class for notification adapters that use aiohttp.

    Subclasses must call ``await self._close_http()`` in their
    stop/shutdown, or use the adapter as an async context manager
    which handles cleanup automatically.

    Attributes:
        _http_client: Lazy-initialized ``aiohttp.ClientSession``.
            Created on first call to ``_get_http_client()``.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._http_client: Optional[Any] = None

    def _get_http_client(self) -> Any:
        """Get or create the HTTP client session."""
        if self._http_client is None or self._http_client.closed:
            if not HAS_AIOHTTP:
                raise ImportError("aiohttp is required for notification adapters")
            self._http_client = _aiohttp.ClientSession()
        return self._http_client

    async def _close_http(self) -> None:
        """Close the HTTP client session if open."""
        if self._http_client is not None and not self._http_client.closed:
            await self._http_client.close()
            self._http_client = None

    async def close(self) -> None:
        """Release all resources held by this adapter.

        Subclasses should override to clean up their own resources and
        call ``await super().close()`` at the end.
        """
        await self._close_http()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def __del__(self):
        if self._http_client is not None and not self._http_client.closed:
            import asyncio as _asyncio
            try:
                loop = _asyncio.get_running_loop()
            except RuntimeError:
                _asyncio.run(self._http_client.close())
            else:
                loop.create_task(self._http_client.close())
