"""At most a few live kernels, one per session, least recently used first out (H17).

One call at a time runs in a kernel. A kernel that dies, times out or is evicted takes
its variables with it, and the next call for that session starts a fresh one and says so.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field

from weebot.application.ports.kernel_port import KernelHandle, KernelPort, KernelResult

logger = logging.getLogger(__name__)

MAX_KERNELS = 4
_LOST_REMEMBERED = 256


@dataclass
class _Slot:
    handle: KernelHandle
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False


@dataclass(frozen=True)
class KernelRun:
    result: KernelResult
    notice: str = ""  # why the session's earlier variables are gone, on the call that starts anew


class KernelManager:
    def __init__(self, backend: KernelPort, max_kernels: int = MAX_KERNELS) -> None:
        self._backend = backend
        self._max = max_kernels
        self._slots: OrderedDict[str, _Slot] = OrderedDict()
        self._lost: OrderedDict[str, str] = OrderedDict()  # session -> why its kernel went
        self._guard = asyncio.Lock()

    @property
    def live_sessions(self) -> list[str]:
        """Sessions with a kernel, least recently used first."""
        return list(self._slots)

    async def run(
        self, session_id: str, code: str, timeout: float, *, reset: bool = False
    ) -> KernelRun:
        notice = ""
        async with self._guard:
            if reset:
                await self._drop(session_id, "", remember=False)
            slot = self._slots.get(session_id)
            if slot is None:
                slot = await self._start(session_id)
                notice = self._lost.pop(session_id, "")
            self._slots.move_to_end(session_id)
        async with slot.lock:
            if slot.closed:  # stopped while this call waited its turn
                return await self.run(session_id, code, timeout)
            result = await self._backend.exec(slot.handle, code, timeout)
        if result.died:
            async with self._guard:
                if self._slots.get(session_id) is slot:
                    await self._drop(session_id, result.error or "it stopped")
        return KernelRun(result, notice)

    async def stop_session(self, session_id: str) -> int:
        """Stop the session's kernel (session deleted). Returns how many were stopped."""
        async with self._guard:
            self._lost.pop(session_id, None)
            return int(await self._drop(session_id, "", remember=False))

    async def stop_all(self) -> None:
        async with self._guard:
            for session_id in list(self._slots):
                await self._drop(session_id, "", remember=False)

    async def _start(self, session_id: str) -> _Slot:
        while len(self._slots) >= self._max:
            idle = next((s for s, slot in self._slots.items() if not slot.lock.locked()), None)
            if idle is None:
                raise RuntimeError(f"All {self._max} kernels are busy; try again shortly.")
            await self._drop(idle, "its kernel was stopped to make room for another session")
        slot = _Slot(await self._backend.start(session_id))
        self._slots[session_id] = slot
        return slot

    async def _drop(self, session_id: str, why: str, *, remember: bool = True) -> bool:
        slot = self._slots.pop(session_id, None)
        if slot is None:
            return False
        slot.closed = True
        try:
            await self._backend.stop(slot.handle)
        except Exception:
            logger.warning("Stopping a kernel failed for session %s", session_id, exc_info=True)
        if remember and why:
            self._lost[session_id] = why
            while len(self._lost) > _LOST_REMEMBERED:
                self._lost.popitem(last=False)
        return True
