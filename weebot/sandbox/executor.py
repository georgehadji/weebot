"""SandboxedExecutor — runs external processes safely with timeout + memory limits."""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ExecutionResult:
    """Result from a sandboxed subprocess execution."""

    stdout: str
    stderr: str
    returncode: int
    elapsed_ms: float
    timed_out: bool = False
    memory_killed: bool = False

    @property
    def success(self) -> bool:
        """True only when the process exited cleanly with code 0."""
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.memory_killed
        )

    @property
    def combined_output(self) -> str:
        """Merge stdout and stderr into a single string for ToolResult.output."""
        parts: list[str] = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr]\n{self.stderr}")
        return "\n".join(parts) if parts else "(no output)"


# ---------------------------------------------------------------------------
# Internal memory monitor
# ---------------------------------------------------------------------------

def _psutil_memory_monitor(
    pid: int,
    limit_bytes: int,
    stop_event: threading.Event,
    killed_flag: list[bool],
) -> None:
    """Background thread: kill process if RSS exceeds limit_bytes.

    Runs every 0.5 s until stop_event is set or the process dies.
    All exceptions are caught silently so the monitor never crashes the host.
    """
    try:
        import psutil  # optional dependency — graceful if absent
        proc = psutil.Process(pid)
        while not stop_event.wait(timeout=0.5):
            try:
                if proc.memory_info().rss > limit_bytes:
                    proc.kill()
                    killed_flag[0] = True
                    return
            except psutil.NoSuchProcess:
                return  # process already gone — normal
    except Exception:
        pass  # psutil not installed or any other error — degrade gracefully


# ---------------------------------------------------------------------------
# SandboxedExecutor
# ---------------------------------------------------------------------------

class SandboxedExecutor:
    """
    Runs an external process with timeout enforcement and optional memory limit.

    Used as an internal helper by BashTool and PythonExecuteTool (not a BaseTool).
    All blocking I/O is handled via asyncio so the event loop is never stalled.

    Args:
        max_output_bytes: Maximum bytes captured from stdout/stderr each stream.
                          Output beyond this is truncated with a '[truncated]'
                          suffix. Default: 65 536 (64 KB).
        memory_limit_mb:  Optional RSS memory cap in megabytes. Requires psutil.
                          If psutil is unavailable the limit is silently ignored.
                          Default: None (no memory limit).
    """

    _TRUNCATION_SUFFIX = b"...[truncated]"

    def __init__(
        self,
        max_output_bytes: int = 65_536,
        memory_limit_mb: Optional[int] = None,
    ) -> None:
        self._max_output_bytes = max_output_bytes
        self._memory_limit_bytes: Optional[int] = (
            memory_limit_mb * 1024 * 1024 if memory_limit_mb is not None else None
        )

    async def run(
        self,
        cmd: list[str],
        timeout: float = 30.0,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """Launch *cmd* as a subprocess and return an ExecutionResult.

        stdout and stderr are captured separately.  If the process does not
        finish within *timeout* seconds it is killed and the result has
        ``timed_out=True``.  Each stream is independently truncated at
        ``max_output_bytes``.

        Args:
            cmd:     Command list, e.g. ``["python", "-c", "print('hi')"]``.
            timeout: Seconds before the process is killed. Default 30.
            cwd:     Working directory. Default: inherited from parent process.
            env:     Environment variables. Default: inherited from parent.

        Returns:
            ExecutionResult with stdout, stderr, returncode, elapsed_ms, and
            boolean flags timed_out / memory_killed.
        """
        t_start = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
        )

        # Optional psutil memory monitor running in a background thread.
        stop_event = threading.Event()
        memory_killed: list[bool] = [False]
        monitor_task: Optional[asyncio.Task] = None

        if self._memory_limit_bytes is not None:
            monitor_task = asyncio.create_task(
                asyncio.to_thread(
                    _psutil_memory_monitor,
                    proc.pid,
                    self._memory_limit_bytes,
                    stop_event,
                    memory_killed,
                )
            )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed_ms = (time.monotonic() - t_start) * 1000
            return ExecutionResult(
                stdout="",
                stderr=f"Process killed after {timeout:.0f}s timeout.",
                returncode=-1,
                elapsed_ms=elapsed_ms,
                timed_out=True,
            )
        finally:
            # Always stop the memory monitor whether execution succeeded or not.
            stop_event.set()
            if monitor_task is not None:
                try:
                    await monitor_task
                except Exception:
                    pass

        elapsed_ms = (time.monotonic() - t_start) * 1000

        # Truncate each stream independently so both are always preserved.
        stdout_b = self._truncate(stdout_b)
        stderr_b = self._truncate(stderr_b)

        return ExecutionResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode,
            elapsed_ms=elapsed_ms,
            memory_killed=memory_killed[0],
        )

    def _truncate(self, data: bytes) -> bytes:
        """Truncate *data* to max_output_bytes, appending a marker if cut."""
        if len(data) <= self._max_output_bytes:
            return data
        return data[: self._max_output_bytes] + self._TRUNCATION_SUFFIX
