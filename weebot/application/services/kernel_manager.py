"""At most a few live kernels, one per session, least recently used first out (H17).

One call at a time runs in a kernel. A kernel that dies, times out, is cancelled or is
evicted takes its variables with it, and the next call for that session starts a fresh one
and says so.

The table of slots is only ever changed by code that does not await, so one event loop
cannot interleave two changes; a kernel is started and stopped outside any shared lock, so
a slow start for one session never holds up another. The locks are per slot, and are
renewed when the manager is used from a different event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field

from weebot.application.ports.kernel_port import (
    KernelHandle,
    KernelPort,
    KernelResult,
    RpcHandler,
)

logger = logging.getLogger(__name__)

MAX_KERNELS = 4
_LOST_REMEMBERED = 256
_ATTEMPTS = 3  # a call is run again when its kernel was gone before the code reached it


@dataclass
class _Slot:
    handle: KernelHandle | None = None  # None until the kernel has started
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0  # calls running or waiting; a slot with users is never evicted
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
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def live_sessions(self) -> list[str]:
        """Sessions with a kernel, least recently used first."""
        return list(self._slots)

    async def run(
        self,
        session_id: str,
        code: str,
        timeout: float,
        *,
        reset: bool = False,
        on_rpc: RpcHandler | None = None,
    ) -> KernelRun:
        self._bind_loop()
        victims: list[_Slot] = []
        if reset:
            self._lost.pop(session_id, None)
            victims.extend(self._forget(session_id, ""))
        for _ in range(_ATTEMPTS):
            slot, evicted = self._claim(session_id)
            await self._stop_slots([*victims, *evicted])
            victims = []
            try:
                done = await self._run_in(slot, session_id, code, timeout, on_rpc)
            finally:
                slot.users -= 1
            if done is not None:
                return done
        raise RuntimeError("The kernel kept stopping; try again shortly.")

    async def stop_session(self, session_id: str) -> int:
        """Stop the session's kernel (session deleted). Returns how many were stopped."""
        self._lost.pop(session_id, None)
        gone = self._forget(session_id, "")
        await self._stop_slots(gone)
        return len(gone)

    async def stop_all(self) -> None:
        gone = [s for session_id in list(self._slots) for s in self._forget(session_id, "")]
        await self._stop_slots(gone)

    def _bind_loop(self) -> None:
        """Locks belong to the loop they were first waited on; a new loop gets new locks."""
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop = loop
            for slot in self._slots.values():
                slot.lock, slot.users = asyncio.Lock(), 0

    def _claim(self, session_id: str) -> tuple[_Slot, list[_Slot]]:
        """The session's slot, made if it has none, and the idle ones evicted to make room."""
        evicted: list[_Slot] = []
        slot = self._slots.get(session_id)
        if slot is None:
            while len(self._slots) >= self._max:
                idle = next((s for s, other in self._slots.items() if other.users == 0), None)
                if idle is None:
                    raise RuntimeError(f"All {self._max} kernels are busy; try again shortly.")
                evicted.extend(
                    self._forget(idle, "its kernel was stopped to make room for another session")
                )
            slot = self._slots[session_id] = _Slot()
        slot.users += 1
        self._slots.move_to_end(session_id)
        return slot, evicted

    async def _run_in(
        self,
        slot: _Slot,
        session_id: str,
        code: str,
        timeout: float,
        on_rpc: RpcHandler | None,
    ) -> KernelRun | None:
        """The run, or None when the call must be claimed again (its kernel was gone)."""
        async with slot.lock:
            if slot.closed:  # stopped while this call waited its turn
                return None
            notice = ""
            if slot.handle is None:
                try:
                    slot.handle = await self._backend.start(session_id)
                except BaseException:
                    self._forget(session_id, "", only=slot)
                    raise
                notice = self._lost.pop(session_id, "")
            try:
                result = await self._backend.exec(slot.handle, code, timeout, on_rpc)
            except asyncio.CancelledError:
                # The backend ended the process; the slot must not outlive it.
                self._forget(session_id, "the call was cancelled", only=slot)
                await asyncio.shield(self._stop_slots([slot]))
                raise
            if result.died:
                self._forget(session_id, result.error or "it stopped", only=slot)
                await self._stop_slots([slot])
                if not result.ran:
                    return None
            return KernelRun(result, notice)

    def _forget(self, session_id: str, why: str, *, only: _Slot | None = None) -> list[_Slot]:
        """Take the session's slot out of the table, and remember *why* when given."""
        slot = self._slots.get(session_id)
        if slot is None or (only is not None and slot is not only):
            return []
        del self._slots[session_id]
        slot.closed = True
        if why:
            self._lost[session_id] = why
            while len(self._lost) > _LOST_REMEMBERED:
                self._lost.popitem(last=False)
        return [slot]

    async def _stop_slots(self, slots: list[_Slot]) -> None:
        for slot in slots:
            if slot.handle is None:
                continue
            try:
                await self._backend.stop(slot.handle)
            except Exception:
                logger.warning("Stopping a kernel failed", exc_info=True)
