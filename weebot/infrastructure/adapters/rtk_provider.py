"""
RTK Provider - Enhanced RTK Integration for Weebot

This module provides a comprehensive interface to RTK (Rust Token Killer)
with enhanced functionality for token optimization, command routing, and
analytics tracking.
"""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RTKCommandType(Enum):
    """Types of commands that RTK can optimize."""
    GIT = "git"
    FILE_SYSTEM = "file_system"
    BUILD_TOOL = "build_tool"
    TEST_RUNNER = "test_runner"
    LINTER = "linter"
    CONTAINER = "container"
    CLOUD = "cloud"
    OTHER = "other"


@dataclass
class RTKConfig:
    """Configuration for RTK integration."""
    enabled: bool = True
    ultra_compact: bool = False
    timeout: int = 30
    max_retries: int = 2
    command_types: List[RTKCommandType] = None
    
    def __post_init__(self):
        if self.command_types is None:
            self.command_types = [
                RTKCommandType.GIT,
                RTKCommandType.FILE_SYSTEM,
                RTKCommandType.BUILD_TOOL,
                RTKCommandType.TEST_RUNNER,
                RTKCommandType.LINTER
            ]


class RTKProvider:
    """
    Enhanced RTK provider with comprehensive command optimization capabilities.
    
    Provides intelligent routing to RTK-optimized commands with fallback to
    standard execution when RTK is unavailable or inappropriate.
    """
    
    def __init__(self, config: Optional[RTKConfig] = None):
        self.config = config or RTKConfig()
        self._available = self._check_availability()
        
        # Supported command patterns that benefit from RTK optimization
        self._command_patterns = {
            RTKCommandType.GIT: [
                "git ", "hub ", "gh "
            ],
            RTKCommandType.FILE_SYSTEM: [
                "ls", "find ", "grep ", "tree ", "cat ", "head ", "tail ",
                "wc ", "du ", "df ", "ps ", "top ", "htop "
            ],
            RTKCommandType.BUILD_TOOL: [
                "cargo ", "npm ", "yarn ", "pnpm ", "go ", "rustc ",
                "gcc ", "clang ", "make ", "cmake ", "bazel "
            ],
            RTKCommandType.TEST_RUNNER: [
                "pytest ", "cargo test", "go test", "npm test", "yarn test",
                "python -m pytest", "unittest ", "jest ", "mocha ", "vitest "
            ],
            RTKCommandType.LINTER: [
                "ruff ", "eslint ", "prettier ", "biome ", "tsc ", "mypy ",
                "flake8 ", "black ", "isort ", "pylint "
            ],
            RTKCommandType.CONTAINER: [
                "docker ", "podman ", "kubectl ", "helm ", "minikube "
            ],
            RTKCommandType.CLOUD: [
                "aws ", "gcloud ", "az ", "terraform ", "pulumi "
            ]
        }
    
    def _check_availability(self) -> bool:
        """Check if RTK is available in the system."""
        try:
            result = subprocess.run(
                ["rtk", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def is_available(self) -> bool:
        """Check if RTK is available."""
        return self._available
    
    def get_command_type(self, command: str) -> Optional[RTKCommandType]:
        """Determine the type of command for RTK optimization."""
        command_lower = command.strip().lower()
        
        for cmd_type, patterns in self._command_patterns.items():
            for pattern in patterns:
                if command_lower.startswith(pattern):
                    return cmd_type
        
        return None
    
    def should_optimize_command(self, command: str) -> bool:
        """Determine if a command should be optimized with RTK."""
        if not self.config.enabled or not self.is_available():
            return False
        
        cmd_type = self.get_command_type(command)
        return cmd_type in self.config.command_types
    
    def transform_command(self, command: str) -> str:
        """Transform a command to use RTK equivalent."""
        parts = command.strip().split()
        if not parts:
            return command
        
        main_cmd = parts[0]
        args = parts[1:]
        
        # Special handling for different command types
        if main_cmd in ["git", "hub", "gh"]:
            return f"rtk git {' '.join(args)}"
        elif main_cmd in ["ls", "find", "grep", "tree", "cat", "head", "tail", "wc", "du", "df", "ps", "top", "htop"]:
            return f"rtk {main_cmd} {' '.join(args)}"
        elif main_cmd in ["cargo", "npm", "yarn", "pnpm", "go", "rustc", "gcc", "clang", "make", "cmake", "bazel"]:
            return f"rtk {main_cmd} {' '.join(args)}"
        elif main_cmd in ["pytest", "unittest", "jest", "mocha", "vitest"] or "test" in command_lower:
            return f"rtk test {command}"
        elif main_cmd in ["ruff", "eslint", "prettier", "biome", "tsc", "mypy", "flake8", "black", "isort", "pylint"]:
            return f"rtk {main_cmd} {' '.join(args)}"
        elif main_cmd in ["docker", "podman", "kubectl", "helm", "minikube"]:
            return f"rtk {main_cmd} {' '.join(args)}"
        elif main_cmd in ["aws", "gcloud", "az", "terraform", "pulumi"]:
            return f"rtk {main_cmd} {' '.join(args)}"
        else:
            # For other commands, use rtk err to show only errors/warnings
            return f"rtk err {command}"
    
    async def execute_with_optimization(
        self,
        command: str,
        timeout: Optional[float] = None
    ) -> Tuple[str, str, int]:
        """
        Execute a command with RTK optimization if beneficial.
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds (defaults to config value)
            
        Returns:
            Tuple of (stdout, stderr, returncode)
        """
        effective_timeout = timeout or self.config.timeout
        
        if not self.should_optimize_command(command):
            # Execute directly if RTK optimization not appropriate
            return await self._execute_directly(command, effective_timeout)
        
        # Transform command for RTK optimization
        rtk_command = self.transform_command(command)
        logger.info(f"Executing command with RTK optimization: {rtk_command}")
        
        try:
            # Execute through RTK
            proc = await asyncio.create_subprocess_shell(
                rtk_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=65536  # 64KB limit to match SandboxedExecutor
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
            return stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace'), proc.returncode
            
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"RTK command timed out after {effective_timeout}s", -1
        except Exception as e:
            logger.warning(f"RTK execution failed: {e}, falling back to direct execution")
            # Fall back to direct execution
            return await self._execute_directly(command, effective_timeout)
    
    async def _execute_directly(self, command: str, timeout: float) -> Tuple[str, str, int]:
        """Execute command directly without RTK optimization."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=65536  # 64KB limit to match SandboxedExecutor
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode('utf-8', errors='replace'), stderr.decode('utf-8', errors='replace'), proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "", f"Command timed out after {timeout}s", -1
    
    async def get_token_savings_estimate(self, command: str) -> Dict[str, Any]:
        """
        Estimate potential token savings for a command.
        
        Args:
            command: Command to analyze
            
        Returns:
            Dictionary with savings estimates
        """
        cmd_type = self.get_command_type(command)
        
        if cmd_type == RTKCommandType.GIT:
            return {
                "command_type": "git",
                "estimated_savings_percentage": 80,
                "typical_raw_tokens": 300,
                "typical_optimized_tokens": 60
            }
        elif cmd_type == RTKCommandType.FILE_SYSTEM:
            return {
                "command_type": "file_system",
                "estimated_savings_percentage": 75,
                "typical_raw_tokens": 800,
                "typical_optimized_tokens": 200
            }
        elif cmd_type == RTKCommandType.BUILD_TOOL:
            return {
                "command_type": "build_tool",
                "estimated_savings_percentage": 85,
                "typical_raw_tokens": 25000,
                "typical_optimized_tokens": 3750
            }
        elif cmd_type == RTKCommandType.TEST_RUNNER:
            return {
                "command_type": "test_runner",
                "estimated_savings_percentage": 90,
                "typical_raw_tokens": 15000,
                "typical_optimized_tokens": 1500
            }
        elif cmd_type == RTKCommandType.LINTER:
            return {
                "command_type": "linter",
                "estimated_savings_percentage": 80,
                "typical_raw_tokens": 5000,
                "typical_optimized_tokens": 1000
            }
        elif cmd_type == RTKCommandType.CONTAINER:
            return {
                "command_type": "container",
                "estimated_savings_percentage": 75,
                "typical_raw_tokens": 1000,
                "typical_optimized_tokens": 250
            }
        else:
            return {
                "command_type": "other",
                "estimated_savings_percentage": 0,
                "typical_raw_tokens": 0,
                "typical_optimized_tokens": 0
            }
    
    async def batch_optimize_commands(self, commands: List[str]) -> List[Dict[str, Any]]:
        """
        Optimize a batch of commands and return execution results.
        
        Args:
            commands: List of commands to optimize and execute
            
        Returns:
            List of execution results with optimization metadata
        """
        results = []
        
        for command in commands:
            savings_estimate = await self.get_token_savings_estimate(command)
            should_optimize = self.should_optimize_command(command)
            
            if should_optimize:
                stdout, stderr, returncode = await self.execute_with_optimization(command)
                results.append({
                    "command": command,
                    "optimized": True,
                    "rtk_command": self.transform_command(command),
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                    "savings_estimate": savings_estimate
                })
            else:
                stdout, stderr, returncode = await self._execute_directly(command, self.config.timeout)
                results.append({
                    "command": command,
                    "optimized": False,
                    "rtk_command": None,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                    "savings_estimate": savings_estimate
                })
        
        return results


# Global RTK provider instance
_rtk_provider: Optional[RTKProvider] = None


def get_rtk_provider() -> RTKProvider:
    """
    Get the global RTK provider instance.
    
    Returns:
        RTKProvider instance
    """
    global _rtk_provider
    if _rtk_provider is None:
        _rtk_provider = RTKProvider()
    return _rtk_provider


async def execute_command_with_token_optimization(
    command: str,
    timeout: Optional[float] = None
) -> Tuple[str, str, int]:
    """
    Execute a command with token optimization via RTK.
    
    Args:
        command: Command to execute
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (stdout, stderr, returncode)
    """
    provider = get_rtk_provider()
    return await provider.execute_with_optimization(command, timeout)


async def estimate_token_savings(command: str) -> Dict[str, Any]:
    """
    Estimate token savings for a command using RTK.
    
    Args:
        command: Command to analyze
        
    Returns:
        Dictionary with savings estimates
    """
    provider = get_rtk_provider()
    return await provider.get_token_savings_estimate(command)