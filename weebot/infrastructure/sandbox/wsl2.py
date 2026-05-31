"""WSL2Sandbox — Windows Subsystem for Linux execution."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)


class WSL2Sandbox(SandboxPort):
    """Sandbox implementation using Windows Subsystem for Linux (WSL2).
    
    This sandbox runs commands in a Linux environment via WSL2, providing
    access to Linux tools and a more traditional Unix-like environment.
    
    Requires WSL2 to be installed and configured on the Windows machine.
    
    Example:
        sandbox = WSL2Sandbox()
        if await sandbox.is_available():
            result = await sandbox.execute(["ls", "-la"])
            print(result.stdout)
    """
    
    _TRUNCATION_SUFFIX = b"...[truncated]"
    
    def __init__(
        self,
        config: Optional[SandboxConfig] = None,
        distribution: Optional[str] = None,
    ) -> None:
        """Initialize the WSL2 sandbox.
        
        Args:
            config: Sandbox configuration. Uses defaults if None.
            distribution: Specific WSL distribution to use (e.g., "Ubuntu").
                         Uses default distribution if None.
        """
        self._config = config or SandboxConfig()
        self._distribution = distribution
        self._memory_limit_bytes: Optional[int] = (
            self._config.memory_limit_mb * 1024 * 1024
            if self._config.memory_limit_mb is not None
            else None
        )
    
    @property
    def sandbox_type(self) -> SandboxType:
        """Return the type of this sandbox."""
        return SandboxType.WSL2
    
    async def is_available(self) -> bool:
        """Check if WSL2 is available on this system."""
        if shutil.which("wsl") is None:
            return False
        
        try:
            # Check WSL status
            proc = await asyncio.create_subprocess_exec(
                "wsl",
                "--status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return proc.returncode == 0
        except Exception:
            return False
    
    def get_capabilities(self) -> set[SandboxCapability]:
        """Return capabilities supported by WSL2."""
        capabilities = {
            SandboxCapability.BASH,
            SandboxCapability.PYTHON,
            SandboxCapability.FILE_SYSTEM,
        }
        
        if self._config.allow_network:
            capabilities.add(SandboxCapability.NETWORK_ACCESS)
        
        return capabilities
    
    def _build_wsl_command(self, command: list[str]) -> list[str]:
        """Build the WSL command with optional distribution."""
        wsl_cmd = ["wsl"]
        if self._distribution:
            wsl_cmd.extend(["-d", self._distribution])
        wsl_cmd.extend(command)
        return wsl_cmd
    
    async def execute(
        self,
        command: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a command in WSL2.
        
        Args:
            command: Command list to execute inside WSL.
            timeout: Timeout in seconds. Uses config default if None.
            cwd: Working directory (will be translated to WSL path if on Windows drive).
            env: Additional environment variables.
        
        Returns:
            SandboxResult with execution details.
        """
        if not await self.is_available():
            return SandboxResult(
                stdout="",
                stderr="WSL2 is not available on this system",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )
        
        timeout = timeout or self._config.timeout
        
        if timeout <= 0:
            return SandboxResult(
                stdout="",
                stderr=f"Invalid timeout {timeout!r}: must be > 0 seconds.",
                returncode=-1,
                elapsed_ms=0.0,
                sandbox_type=self.sandbox_type,
            )
        
        # Build WSL command
        wsl_command = self._build_wsl_command(command)
        
        # Merge environment variables
        merged_env = dict(self._config.env_vars)
        if env:
            merged_env.update(env)
        
        # Handle working directory
        working_dir = cwd or self._config.working_dir
        
        import time
        t_start = time.monotonic()
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *wsl_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir) if working_dir is not None else None,
                env=merged_env if merged_env else None,
            )
            
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            
        except asyncio.TimeoutError:
            return SandboxResult(
                stdout="",
                stderr=f"Process killed after {timeout:.0f}s timeout.",
                returncode=-1,
                elapsed_ms=(time.monotonic() - t_start) * 1000,
                timed_out=True,
                sandbox_type=self.sandbox_type,
            )
        except Exception as e:
            return SandboxResult(
                stdout="",
                stderr=f"Failed to execute in WSL: {e}",
                returncode=-1,
                elapsed_ms=(time.monotonic() - t_start) * 1000,
                sandbox_type=self.sandbox_type,
            )
        
        elapsed_ms = (time.monotonic() - t_start) * 1000
        
        # Truncate output
        stdout_b = self._truncate(stdout_b)
        stderr_b = self._truncate(stderr_b)
        
        return SandboxResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else -1,
            elapsed_ms=elapsed_ms,
            sandbox_type=self.sandbox_type,
        )
    
    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a shell script in WSL2.
        
        Args:
            script: Shell script to execute.
            shell: Shell type ("bash", "sh", "zsh").
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
        
        Returns:
            SandboxResult with execution details.
        """
        command = [shell, "-c", script]
        return await self.execute(command, timeout, cwd, env)
    
    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute Python code in WSL2.
        
        Args:
            code: Python code to execute.
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Additional environment variables.
        
        Returns:
            SandboxResult with execution details.
        """
        command = ["python3", "-c", code]
        return await self.execute(command, timeout, cwd, env)
    
    def _truncate(self, data: bytes) -> bytes:
        """Truncate data to max_output_bytes."""
        max_bytes = self._config.max_output_bytes
        if len(data) <= max_bytes:
            return data
        return data[:max_bytes] + self._TRUNCATION_SUFFIX
    
    async def list_distributions(self) -> list[str]:
        """List available WSL distributions.
        
        Returns:
            List of distribution names.
        """
        if not await self.is_available():
            return []
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "wsl",
                "-l",
                "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            
            # Parse output (names may have special characters)
            distros = []
            for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                line = line.strip()
                if line:
                    # Remove null bytes and default marker
                    line = line.replace("\x00", "").replace(" (Default)", "").strip()
                    if line:
                        distros.append(line)
            return distros
        except Exception:
            return []
