"""SandboxFactory — factory for creating sandbox instances.

Provides auto-detection and selection of the best available sandbox
for the current environment.
"""
from __future__ import annotations

import logging
from typing import Optional

from weebot.application.ports.sandbox_port import (
    SandboxCapability,
    SandboxConfig,
    SandboxPort,
    SandboxResult,
    SandboxType,
)
from weebot.infrastructure.sandbox.native_windows import NativeWindowsSandbox
from weebot.infrastructure.sandbox.wsl2 import WSL2Sandbox

try:
    from weebot.infrastructure.sandbox.docker_linux import DockerLinuxSandbox
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

logger = logging.getLogger(__name__)


class SandboxFactory:
    """Factory for creating and selecting sandbox implementations.
    
    The factory can auto-detect the best available sandbox or create
    specific implementations as requested.
    
    Priority order for auto-selection:
    1. Docker (most isolated)
    2. WSL2 (Linux environment on Windows)
    3. Native Windows (fallback)
    
    Example:
        factory = SandboxFactory()
        
        # Auto-select best sandbox
        sandbox = factory.create_default()
        
        # Create specific sandbox
        docker = factory.create(SandboxType.DOCKER_LINUX)
        
        # Create with custom config
        config = SandboxConfig(timeout=60.0, memory_limit_mb=512)
        sandbox = factory.create_default(config)
    """
    
    # Priority order for auto-selection (most isolated first)
    DEFAULT_PRIORITY = [
        SandboxType.DOCKER_LINUX,
        SandboxType.WSL2,
        SandboxType.NATIVE_WINDOWS,
    ]
    
    def __init__(self):
        """Initialize the sandbox factory."""
        self._sandbox_classes: dict[SandboxType, type[SandboxPort]] = {
            SandboxType.NATIVE_WINDOWS: NativeWindowsSandbox,
            SandboxType.WSL2: WSL2Sandbox,
        }
        
        if DOCKER_AVAILABLE:
            self._sandbox_classes[SandboxType.DOCKER_LINUX] = DockerLinuxSandbox
    
    async def detect_available(
        self,
        required_capabilities: Optional[set[SandboxCapability]] = None,
    ) -> list[SandboxType]:
        """Detect available sandbox types on this system.
        
        Args:
            required_capabilities: If specified, only return sandboxes
                that support all these capabilities.
        
        Returns:
            List of available sandbox types, ordered by priority.
        """
        available: list[SandboxType] = []
        
        for sandbox_type in self.DEFAULT_PRIORITY:
            if sandbox_type not in self._sandbox_classes:
                continue
            
            try:
                sandbox_class = self._sandbox_classes[sandbox_type]
                instance = sandbox_class()
                
                if await instance.is_available():
                    if required_capabilities is None:
                        available.append(sandbox_type)
                    elif required_capabilities.issubset(instance.get_capabilities()):
                        available.append(sandbox_type)
            except Exception as e:
                logger.debug(f"Error checking {sandbox_type.name}: {e}")
        
        return available
    
    def create(
        self,
        sandbox_type: SandboxType,
        config: Optional[SandboxConfig] = None,
    ) -> SandboxPort:
        """Create a specific sandbox implementation.
        
        Args:
            sandbox_type: The type of sandbox to create.
            config: Optional configuration for the sandbox.
        
        Returns:
            Configured sandbox instance.
        
        Raises:
            ValueError: If the sandbox type is unknown or not available.
        """
        if sandbox_type not in self._sandbox_classes:
            raise ValueError(f"Unknown sandbox type: {sandbox_type.name}")
        
        sandbox_class = self._sandbox_classes[sandbox_type]
        return sandbox_class(config)
    
    async def create_default(
        self,
        config: Optional[SandboxConfig] = None,
        required_capabilities: Optional[set[SandboxCapability]] = None,
    ) -> SandboxPort:
        """Create the best available sandbox.
        
        Selects the highest-priority sandbox that is available on this
        system and supports the required capabilities.
        
        Args:
            config: Optional configuration for the sandbox.
            required_capabilities: Required capabilities for the sandbox.
        
        Returns:
            Configured sandbox instance.
        
        Raises:
            RuntimeError: If no suitable sandbox is available.
        """
        available = await self.detect_available(required_capabilities)
        
        if not available:
            if required_capabilities:
                raise RuntimeError(
                    f"No sandbox available with capabilities: {required_capabilities}"
                )
            else:
                raise RuntimeError("No sandbox available on this system")
        
        selected = available[0]
        logger.info(f"Auto-selected sandbox: {selected.name}")
        
        return self.create(selected, config)
    
    async def create_fallback_chain(
        self,
        config: Optional[SandboxConfig] = None,
    ) -> FallbackSandboxChain:
        """Create a fallback chain of sandboxes.
        
        The fallback chain tries each sandbox in order until one succeeds.
        
        Args:
            config: Optional configuration for sandboxes.
        
        Returns:
            FallbackSandboxChain instance.
        """
        available = await self.detect_available()
        sandboxes = [self.create(st, config) for st in available]
        return FallbackSandboxChain(sandboxes)


class FallbackSandboxChain:
    """Chain of sandboxes that falls back on failure.
    
    Attempts to execute with each sandbox in order until one succeeds.
    Useful for resilient execution across different environments.
    
    Example:
        chain = await factory.create_fallback_chain()
        result = await chain.execute(["python", "-c", "print('hello')"])
    """
    
    def __init__(self, sandboxes: list[SandboxPort]):
        """Initialize with a list of sandboxes to try.
        
        Args:
            sandboxes: Ordered list of sandboxes to attempt.
        """
        self._sandboxes = sandboxes
    
    async def execute(
        self,
        command: list[str],
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute command with fallback.
        
        Tries each sandbox in order until one succeeds (returncode == 0)
        or all have been attempted.
        
        Args:
            command: Command to execute.
            timeout: Timeout in seconds.
            cwd: Working directory.
            env: Environment variables.
        
        Returns:
            SandboxResult from the first successful sandbox, or the last
            attempted sandbox if all failed.
        """
        last_result: Optional[SandboxResult] = None
        
        for sandbox in self._sandboxes:
            try:
                result = await sandbox.execute(command, timeout, cwd, env)
                last_result = result
                
                if result.success:
                    return result
                
                logger.debug(
                    f"Sandbox {sandbox.sandbox_type.name} failed with rc={result.returncode}"
                )
            except Exception as e:
                logger.warning(f"Sandbox {sandbox.sandbox_type.name} error: {e}")
        
        # Return last result or error if none attempted
        if last_result is not None:
            return last_result
        
        return SandboxResult(
            stdout="",
            stderr="No sandboxes available in fallback chain",
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=SandboxType.NATIVE_WINDOWS,
        )
    
    async def execute_shell(
        self,
        script: str,
        shell: str = "bash",
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute shell script with fallback."""
        last_result: Optional[SandboxResult] = None
        
        for sandbox in self._sandboxes:
            try:
                result = await sandbox.execute_shell(script, shell, timeout, cwd, env)
                last_result = result
                
                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"Sandbox {sandbox.sandbox_type.name} error: {e}")
        
        if last_result is not None:
            return last_result
        
        return SandboxResult(
            stdout="",
            stderr="No sandboxes available in fallback chain",
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=SandboxType.NATIVE_WINDOWS,
        )
    
    async def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute Python code with fallback."""
        last_result: Optional[SandboxResult] = None
        
        for sandbox in self._sandboxes:
            try:
                result = await sandbox.execute_python(code, timeout, cwd, env)
                last_result = result
                
                if result.success:
                    return result
            except Exception as e:
                logger.warning(f"Sandbox {sandbox.sandbox_type.name} error: {e}")
        
        if last_result is not None:
            return last_result
        
        return SandboxResult(
            stdout="",
            stderr="No sandboxes available in fallback chain",
            returncode=-1,
            elapsed_ms=0.0,
            sandbox_type=SandboxType.NATIVE_WINDOWS,
        )


# Convenience functions for quick access

async def get_default_sandbox(config: Optional[SandboxConfig] = None) -> SandboxPort:
    """Get the best available sandbox.
    
    Args:
        config: Optional configuration.
    
    Returns:
        Best available sandbox instance.
    """
    factory = SandboxFactory()
    return await factory.create_default(config)


def get_sandbox(
    sandbox_type: SandboxType,
    config: Optional[SandboxConfig] = None,
) -> SandboxPort:
    """Get a specific sandbox type.
    
    Args:
        sandbox_type: Type of sandbox to create.
        config: Optional configuration.
    
    Returns:
        Configured sandbox instance.
    """
    factory = SandboxFactory()
    return factory.create(sandbox_type, config)
