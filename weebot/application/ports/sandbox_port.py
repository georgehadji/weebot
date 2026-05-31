"""SandboxPort — abstraction for code execution environments.

This port defines the interface for running commands in various sandboxed
environments (native Windows, Docker, WSL2, etc.).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional


class SandboxType(Enum):
    """Types of sandbox environments available."""
    NATIVE_WINDOWS = auto()
    NATIVE_LINUX = auto()
    DOCKER_LINUX = auto()
    WSL2 = auto()
    KUBERNETES = auto()


class SandboxCapability(Enum):
    """Capabilities that a sandbox may support."""
    BASH = auto()
    POWERSHELL = auto()
    PYTHON = auto()
    NETWORK_ACCESS = auto()
    FILE_SYSTEM = auto()
    GPU_ACCESS = auto()


@dataclass(frozen=True)
class SandboxResult:
    """Result from a sandboxed command execution.
    
    Attributes:
        stdout: Standard output from the command.
        stderr: Standard error from the command.
        returncode: Process exit code (0 = success).
        elapsed_ms: Execution time in milliseconds.
        timed_out: True if execution exceeded timeout.
        memory_killed: True if process was killed due to memory limit.
        sandbox_type: The type of sandbox that executed the command.
    """
    stdout: str
    stderr: str
    returncode: int
    elapsed_ms: float
    timed_out: bool = False
    memory_killed: bool = False
    sandbox_type: SandboxType = SandboxType.NATIVE_WINDOWS
    
    @property
    def success(self) -> bool:
        """True only when the process exited cleanly with code 0."""
        return self.returncode == 0 and not self.timed_out and not self.memory_killed
    
    @property
    def combined_output(self) -> str:
        """Merge stdout and stderr into a single string."""
        parts: list[str] = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr]\n{self.stderr}")
        return "\n".join(parts) if parts else "(no output)"


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution.
    
    Attributes:
        timeout: Default timeout in seconds.
        max_output_bytes: Maximum bytes to capture from stdout/stderr.
        memory_limit_mb: Optional memory limit in megabytes.
        allow_network: Whether to allow network access.
        working_dir: Default working directory for commands.
        env_vars: Additional environment variables.
        read_only_paths: Paths to mount as read-only (Docker/K8s).
        read_write_paths: Paths to mount as read-write (Docker/K8s).
    """
    timeout: float = 30.0
    max_output_bytes: int = 65_536
    memory_limit_mb: Optional[int] = None
    allow_network: bool = True
    working_dir: Optional[Path] = None
    env_vars: dict[str, str] = None
    read_only_paths: list[Path] = None
    read_write_paths: list[Path] = None
    
    def __post_init__(self):
        if self.env_vars is None:
            self.env_vars = {}
        if self.read_only_paths is None:
            self.read_only_paths = []
        if self.read_write_paths is None:
            self.read_write_paths = []


class SandboxPort(ABC):
    """Abstract base class for sandbox execution environments.
    
    Implementations provide isolated execution of commands with configurable
    security boundaries, resource limits, and environment settings.
    
    Example:
        sandbox = NativeWindowsSandbox()
        result = await sandbox.execute(
            ["python", "-c", "print('hello')"],
            timeout=10.0
        )
        if result.success:
            print(result.stdout)
    """
    
    @property
    @abstractmethod
    def sandbox_type(self) -> SandboxType:
        """Return the type of this sandbox implementation."""
        ...
    
    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this sandbox environment is available on the current system.
        
        Returns:
            True if the sandbox can be used (e.g., Docker is installed,
            WSL2 is enabled, etc.).
        """
        ...
    
    @abstractmethod
    def get_capabilities(self) -> set[SandboxCapability]:
        """Return the set of capabilities this sandbox supports."""
        ...
    
    @abstractmethod
    async def execute(
        self,
        command: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a command in the sandboxed environment.
        
        Args:
            command: Command list, e.g., ["python", "-c", "print('hi')"].
            timeout: Seconds before the process is killed. Uses config default if None.
            cwd: Working directory. Uses config default if None.
            env: Additional environment variables. Merged with config env_vars.
        
        Returns:
            SandboxResult with execution details.
        """
        ...
    
    @abstractmethod
    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute a shell script in the sandboxed environment.
        
        Args:
            script: The shell script to execute.
            shell: Shell type ("bash", "powershell", "sh", etc.).
            timeout: Seconds before the process is killed.
            cwd: Working directory.
            env: Additional environment variables.
        
        Returns:
            SandboxResult with execution details.
        """
        ...
    
    @abstractmethod
    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str | Path] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute Python code in the sandboxed environment.
        
        Args:
            code: Python code to execute.
            timeout: Seconds before the process is killed.
            cwd: Working directory.
            env: Additional environment variables.
        
        Returns:
            SandboxResult with execution details.
        """
        ...
    
    def has_capability(self, capability: SandboxCapability) -> bool:
        """Check if this sandbox supports a specific capability."""
        return capability in self.get_capabilities()
    
    async def check_health(self) -> tuple[bool, str]:
        """Check the health of the sandbox environment.
        
        Returns:
            Tuple of (is_healthy, status_message).
        """
        if not await self.is_available():
            return False, f"{self.sandbox_type.name} is not available"
        return True, f"{self.sandbox_type.name} is healthy"
