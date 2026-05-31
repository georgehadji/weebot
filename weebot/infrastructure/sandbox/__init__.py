"""Sandbox infrastructure adapters.

This module provides various sandbox implementations for isolated code execution:
- NativeWindowsSandbox: Direct Windows process execution with limits
- DockerLinuxSandbox: Docker container-based Linux execution
- WSL2Sandbox: Windows Subsystem for Linux execution
"""
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

__all__ = [
    "SandboxCapability",
    "SandboxConfig",
    "SandboxPort",
    "SandboxResult",
    "SandboxType",
    "NativeWindowsSandbox",
    "WSL2Sandbox",
    "DockerLinuxSandbox",
    "DOCKER_AVAILABLE",
    "get_available_sandboxes",
    "create_sandbox",
]


def get_available_sandboxes() -> list[type[SandboxPort]]:
    """Return a list of available sandbox implementations on this system."""
    sandboxes: list[type[SandboxPort]] = [NativeWindowsSandbox]
    
    # Check WSL2
    import subprocess
    try:
        result = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            timeout=3,
        )
        if result.returncode == 0:
            sandboxes.append(WSL2Sandbox)
    except Exception:
        pass
    
    # Check Docker
    if DOCKER_AVAILABLE:
        sandboxes.append(DockerLinuxSandbox)
    
    return sandboxes


def create_sandbox(
    sandbox_type: SandboxType | None = None,
    config: SandboxConfig | None = None,
) -> SandboxPort:
    """Factory function to create a sandbox instance.
    
    Args:
        sandbox_type: Specific type to create, or None for auto-selection.
        config: Optional configuration for the sandbox.
    
    Returns:
        Configured SandboxPort instance.
    
    Raises:
        RuntimeError: If the requested sandbox type is not available.
    """
    from weebot.infrastructure.sandbox.factory import SandboxFactory
    
    factory = SandboxFactory()
    
    if sandbox_type is None:
        return factory.create_default(config)
    
    return factory.create(sandbox_type, config)
