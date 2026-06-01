"""
RTK Integration for Weebot - Token Economy Implementation

This module provides integration between RTK (Rust Token Killer) and Weebot
to reduce token consumption when executing commands through the BashTool.
"""
import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def is_rtk_available() -> bool:
    """
    Check if RTK is available in the system.
    
    Returns:
        True if rtk command is available, False otherwise
    """
    try:
        result = subprocess.run(['rtk', '--version'], 
                                capture_output=True, 
                                text=True, 
                                timeout=5)
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def should_route_through_rtk(command: str) -> bool:
    """
    Determine if a command should be routed through RTK for token optimization.
    
    Args:
        command: The command string to evaluate
        
    Returns:
        True if the command should be optimized with RTK, False otherwise
    """
    # List of command prefixes that RTK can optimize
    rtk_supported_commands = [
        'git ', 'ls', 'grep ', 'find ', 'cat ', 'tree ', 
        'cargo ', 'npm ', 'yarn ', 'pnpm ', 'go ', 'docker ',
        'kubectl ', 'gh ', 'tsc ', 'eslint', 'ruff ', 'pytest',
        'vitest ', 'playwright ', 'prisma '
    ]
    
    command_lower = command.strip().lower()
    
    # Check if command starts with any of the supported prefixes
    for prefix in rtk_supported_commands:
        if command_lower.startswith(prefix):
            return True
    
    return False


def transform_command_for_rtk(command: str) -> str:
    """
    Transform a command to use RTK equivalent where applicable.
    
    Args:
        command: Original command string
        
    Returns:
        Transformed command string with RTK prefix where applicable
    """
    # Split the command to get the main command part
    parts = command.strip().split()
    if not parts:
        return command
    
    main_cmd = parts[0]
    
    # Special transformations for different commands
    if main_cmd == 'ls':
        # Transform ls commands to rtk ls
        return f"rtk ls {' '.join(parts[1:])}"
    elif main_cmd == 'git':
        # Transform git commands to rtk git
        return f"rtk git {' '.join(parts[1:])}"
    elif main_cmd == 'grep':
        # Transform grep commands to rtk grep
        return f"rtk grep {' '.join(parts[1:])}"
    elif main_cmd == 'find':
        # Transform find commands to rtk find
        return f"rtk find {' '.join(parts[1:])}"
    elif main_cmd == 'cargo':
        # Transform cargo commands to rtk cargo
        return f"rtk cargo {' '.join(parts[1:])}"
    elif main_cmd == 'npm':
        # Transform npm commands to rtk npm
        return f"rtk npm {' '.join(parts[1:])}"
    elif main_cmd == 'docker':
        # Transform docker commands to rtk docker
        return f"rtk docker {' '.join(parts[1:])}"
    elif main_cmd == 'kubectl':
        # Transform kubectl commands to rtk kubectl
        return f"rtk kubectl {' '.join(parts[1:])}"
    elif main_cmd == 'gh':
        # Transform gh commands to rtk gh
        return f"rtk gh {' '.join(parts[1:])}"
    elif main_cmd == 'go':
        # Transform go commands to rtk go
        return f"rtk go {' '.join(parts[1:])}"
    elif main_cmd == 'pytest':
        # Transform pytest commands to rtk pytest
        return f"rtk pytest {' '.join(parts[1:])}"
    elif main_cmd == 'tsc':
        # Transform tsc commands to rtk tsc
        return f"rtk tsc {' '.join(parts[1:])}"
    elif main_cmd in ['eslint', 'biome', 'prettier']:
        # Transform linting/formatter commands to rtk lint
        return f"rtk lint {command}"
    elif main_cmd in ['ruff', 'flake8']:
        # Transform Python linters to rtk ruff
        return f"rtk ruff {command}"
    elif main_cmd in ['vitest', 'playwright']:
        # Transform test runners to rtk test
        return f"rtk {main_cmd} {' '.join(parts[1:])}"
    elif main_cmd == 'prisma':
        # Transform prisma commands to rtk prisma
        return f"rtk prisma {' '.join(parts[1:])}"
    else:
        # For other commands, try to use rtk err or rtk test if it looks like a test/build command
        cmd_str = ' '.join(parts)
        if any(test_cmd in cmd_str for test_cmd in ['test', 'build', 'check', 'lint']):
            return f"rtk test {command}"
        else:
            # For generic commands, use rtk err to show only errors
            return f"rtk err {command}"


async def execute_with_rtk_fallback(command: str, timeout: float = 30.0) -> Tuple[str, str, int]:
    """
    Execute a command through RTK if available, falling back to direct execution.
    
    Args:
        command: Command to execute
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    if not is_rtk_available():
        logger.debug("RTK not available, executing command directly")
        # Fall back to direct execution
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=65536  # 64KB limit to match SandboxedExecutor
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode('utf-8'), stderr.decode('utf-8'), proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"Command timed out after {timeout}s", -1
    
    # RTK is available, check if command should be optimized
    if should_route_through_rtk(command):
        rtk_command = transform_command_for_rtk(command)
        logger.info(f"Routing command through RTK: {rtk_command}")
        
        proc = await asyncio.create_subprocess_shell(
            rtk_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=65536  # 64KB limit to match SandboxedExecutor
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            # RTK should provide optimized output in stdout, with minimal stderr
            return stdout.decode('utf-8'), stderr.decode('utf-8'), proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"RTK command timed out after {timeout}s", -1
    else:
        # Command not suitable for RTK, execute directly
        logger.debug(f"Command not suitable for RTK optimization: {command}")
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=65536  # 64KB limit to match SandboxedExecutor
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode('utf-8'), stderr.decode('utf-8'), proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"Command timed out after {timeout}s", -1


# Global flag to enable/disable RTK integration
RTK_ENABLED = is_rtk_available()


def get_rtk_status() -> dict:
    """
    Get the current status of RTK integration.
    
    Returns:
        Dictionary with RTK status information
    """
    return {
        "available": is_rtk_available(),
        "enabled": RTK_ENABLED,
        "version": get_rtk_version() if is_rtk_available() else None
    }


def get_rtk_version() -> Optional[str]:
    """
    Get the version of RTK installed.
    
    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(['rtk', '--version'], 
                                capture_output=True, 
                                text=True, 
                                timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None