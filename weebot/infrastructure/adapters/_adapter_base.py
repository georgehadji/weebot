"""AsyncSafeAdapter — mixin for adapters with shared mutable async state.

Provides a shared ``asyncio.Lock`` and a snapshot pattern for nullable
refs that can be set to None by ``close()`` concurrently with other
methods.  Adapters that follow this mixin avoid TOCTOU races on instance
refs (the pattern applied to PlaywrightAdapter in BUG-03).

Usage::

    class MyAdapter(AsyncSafeAdapter, SomePort):
        def __init__(self):
            super().__init__()
            self._page: Any | None = None

        async def close(self):
            async with self._state_lock:
                self._page = None

        async def navigate(self, url: str):
            page = await self._snapshot("_page")
            if not page:
                return Error()
            await page.goto(url)
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional


class AsyncSafeAdapter:
    """Mixin for adapters that need thread-safe async state access.

    Provides a shared ``asyncio.Lock`` and a ``_snapshot()`` helper that
    atomically reads an instance attribute under the lock.  Use this for
    nullable refs (like ``self._page``, ``self._context``) that can be
    set to None by ``close()`` while other methods are running.

    The snapshot is taken under lock but then used WITHOUT the lock —
    the local reference is immutable and won't be affected by concurrent
    ``close()`` calls.  This avoids holding the lock across slow I/O.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._state_lock = asyncio.Lock()

    async def _snapshot(self, attr_name: str) -> Optional[Any]:
        """Atomically read an instance attribute under the lock.

        Use this to capture a nullable ref that might be concurrently
        set to None by another coroutine (typically ``close()``).

        Returns:
            The attribute value, or None if the attribute doesn't exist.
        """
        async with self._state_lock:
            return getattr(self, attr_name, None)
