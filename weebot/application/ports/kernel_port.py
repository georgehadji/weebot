"""Port for a Python interpreter that keeps its variables between calls (H17)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class KernelHandle:
    """A started kernel. ``kernel_id`` is private to the backend that made it."""

    session_id: str
    kernel_id: str


@dataclass(frozen=True)
class KernelResult:
    stdout: str = ""
    error: str = ""  # the traceback, or why the run did not finish
    duration_s: float = 0.0
    timed_out: bool = False
    died: bool = False  # the process is gone; its variables with it
    ran: bool = True  # False: the code never reached the kernel, so running it again is safe

    @property
    def success(self) -> bool:
        return not self.error and not self.timed_out and not self.died


class KernelPort(ABC):
    @abstractmethod
    async def start(self, session_id: str) -> KernelHandle:
        """Start a fresh interpreter for a session."""

    @abstractmethod
    async def exec(self, handle: KernelHandle, code: str, timeout: float) -> KernelResult:
        """Run *code* in the kernel's persistent globals. One call at a time per kernel."""

    @abstractmethod
    async def stop(self, handle: KernelHandle) -> None:
        """End the interpreter. Stopping one already gone is not an error."""
