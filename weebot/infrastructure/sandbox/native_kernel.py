"""A persistent Python kernel as a child process of the host (H17).

The same limits as ``NativeWindowsSandbox`` and no more isolation than it has: an
allowlisted environment (no provider keys), the proxy blockade when network is off, and
a memory limit that kills the process. It is a resource wrapper, not a security
boundary. The network is decided once, when the kernel starts: a kernel cannot be
cleared for one call, so a call that needs the network runs one-shot.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from weebot.application.ports.kernel_port import KernelHandle, KernelPort, KernelResult
from weebot.application.ports.sandbox_port import SandboxConfig
from weebot.infrastructure.sandbox.native_windows import (
    sandbox_child_env,
    psutil_memory_monitor,
    spawn_error,
)

logger = logging.getLogger(__name__)

SERVER = Path(__file__).with_name("kernel_server.py")
DEFAULT_MEMORY_MB = 1024
START_TIMEOUT_S = 15.0


@dataclass
class _Running:
    proc: subprocess.Popen
    stop_monitor: threading.Event = field(default_factory=threading.Event)
    memory_killed: list = field(default_factory=lambda: [False])


class NativeKernel(KernelPort):
    def __init__(
        self,
        config: SandboxConfig | None = None,
        *,
        python: str | None = None,
        memory_limit_mb: int | None = None,
        max_output_chars: int = 200_000,
    ) -> None:
        self._config = config or SandboxConfig()
        self._python = python or sys.executable
        self._memory_mb = memory_limit_mb or self._config.memory_limit_mb or DEFAULT_MEMORY_MB
        self._max_chars = max_output_chars
        self._running: dict[str, _Running] = {}

    async def start(self, session_id: str) -> KernelHandle:
        try:
            proc = await asyncio.to_thread(self._spawn)
        except Exception as exc:
            raise RuntimeError(spawn_error(exc)) from exc
        running = _Running(proc)
        try:
            first = await asyncio.wait_for(
                asyncio.to_thread(proc.stdout.readline), timeout=START_TIMEOUT_S
            )
            if not json.loads(first or "{}").get("ready"):
                raise RuntimeError(f"kernel did not start (exit code {proc.poll()})")
        except BaseException as exc:
            self._discard(running)
            if isinstance(exc, (TimeoutError, ValueError)):
                raise RuntimeError(f"kernel did not start: {type(exc).__name__}") from exc
            raise
        limit_bytes = self._memory_mb * 1024 * 1024
        threading.Thread(
            target=psutil_memory_monitor,
            args=(proc.pid, limit_bytes, running.stop_monitor, running.memory_killed),
            daemon=True,
        ).start()
        kernel_id = uuid.uuid4().hex[:8]
        self._running[kernel_id] = running
        return KernelHandle(session_id=session_id, kernel_id=kernel_id)

    def _spawn(self) -> subprocess.Popen:
        cwd = self._config.working_dir or self._config.workspace_dir
        return subprocess.Popen(
            [self._python, "-u", str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(cwd) if cwd is not None else None,
            env=sandbox_child_env(self._config),
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    async def exec(self, handle: KernelHandle, code: str, timeout: float) -> KernelResult:
        running = self._running.get(handle.kernel_id)
        if running is None:
            return KernelResult(error="The kernel is not running.", died=True, ran=False)
        if running.proc.poll() is not None:  # it went between calls, perhaps for memory
            return await self._died(handle, running, 0.0, ran=False)
        started = time.monotonic()
        request = json.dumps({"code": code, "max_chars": self._max_chars}) + "\n"
        try:
            await asyncio.to_thread(self._send, running.proc, request)
            line = await asyncio.wait_for(
                asyncio.to_thread(running.proc.stdout.readline), timeout=timeout
            )
        except TimeoutError:
            self._running.pop(handle.kernel_id, None)
            self._discard(running)
            return KernelResult(
                error=f"Timed out after {timeout:.0f}s; the kernel was stopped.",
                duration_s=time.monotonic() - started,
                timed_out=True,
                died=True,
            )
        except asyncio.CancelledError:
            # What the code was doing is unknown, so its state is not kept.
            self._running.pop(handle.kernel_id, None)
            self._discard(running)
            raise
        except (OSError, ValueError) as exc:
            logger.warning("kernel %s: talking to it failed: %s", handle.kernel_id, exc)
            line = ""
        reply = self._parse(handle, line)
        if reply is None:
            return await self._died(handle, running, time.monotonic() - started)
        stdout = reply.get("stdout", "")
        if reply.get("truncated"):
            stdout += "\n...[output truncated]"
        return KernelResult(
            stdout=stdout,
            error=reply.get("error", ""),
            duration_s=float(reply.get("duration", 0.0)),
        )

    @staticmethod
    def _parse(handle: KernelHandle, line: str) -> dict | None:
        """The reply, or None when the kernel closed its output or died mid-reply."""
        if not line:
            return None
        try:
            return json.loads(line)
        except ValueError:
            logger.warning("kernel %s: its reply was cut short", handle.kernel_id)
            return None

    @staticmethod
    def _send(proc: subprocess.Popen, request: str) -> None:
        proc.stdin.write(request)
        proc.stdin.flush()

    async def _died(
        self, handle: KernelHandle, running: _Running, elapsed: float, *, ran: bool = True
    ) -> KernelResult:
        self._running.pop(handle.kernel_id, None)
        await self._kill(running)
        why = (
            f"memory limit of {self._memory_mb} MB exceeded"
            if running.memory_killed[0]
            else f"exit code {running.proc.poll()}"
        )
        return KernelResult(
            error=f"The kernel stopped ({why}); its variables are gone.",
            duration_s=elapsed,
            died=True,
            ran=ran,
        )

    async def stop(self, handle: KernelHandle) -> None:
        running = self._running.pop(handle.kernel_id, None)
        if running is not None:
            await self._kill(running)

    @staticmethod
    def _terminate(running: _Running) -> None:
        """Ask the OS to end the process now; never waits."""
        running.stop_monitor.set()
        with contextlib.suppress(OSError):
            running.proc.kill()

    @staticmethod
    def _reap(running: _Running) -> None:
        """Wait for the process and release its pipes; blocks, so not on the event loop."""
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            running.proc.wait(timeout=5)
        for stream in (running.proc.stdin, running.proc.stdout):
            with contextlib.suppress(Exception):  # a reader thread may still hold the stream
                stream.close()

    async def _kill(self, running: _Running) -> None:
        self._terminate(running)
        await asyncio.to_thread(self._reap, running)

    def _discard(self, running: _Running) -> None:
        """End the process without waiting; for paths that must not block or may be cancelled."""
        self._terminate(running)
        asyncio.get_running_loop().run_in_executor(None, self._reap, running)
