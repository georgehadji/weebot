"""
Standardized Tool Validation Pipeline

This module provides a consistent validation framework for all tools in the weebot system.
It implements a multi-layer validation approach with security, safety, and business rule checks.
"""
from __future__ import annotations

import abc
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from weebot.tools.base import ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    error_message: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class Validator(abc.ABC):
    """Abstract base class for all validators."""

    @abc.abstractmethod
    async def validate(self, tool_name: str, params: Dict[str, Any]) -> ValidationResult:
        """Validate the tool call parameters."""
        pass


class SecurityValidator(Validator):
    """Validates security aspects of tool calls."""

    # Dangerous patterns that should be blocked
    DANGEROUS_PATTERNS = [
        r'\|\s*bash',  # Pipe to bash
        r'\|\s*sh',    # Pipe to shell
        r'eval\s*\(',  # Eval with parentheses
        r'exec\s*\(',  # Exec with parentheses
        r'\$\(.*\)',  # Command substitution
        r'`\w+`',     # Backtick command substitution
        r'rm\s+-rf\s+/',  # Dangerous rm command
        r'format\s+',  # Format command (Windows)
        r'cipher\s+/w:',  # Cipher wipe command (Windows)
        r'cacls\s+.*\s+/grant\s+everyone:\s*f',  # Grant everyone access
        r'net\s+user\s+.+\s+.+\s+/add',  # Add user command
        r'net\s+localgroup\s+administrators',  # Add to admin group
    ]

    def __init__(self):
        self.patterns = [re.compile(p, re.IGNORECASE) for p in self.DANGEROUS_PATTERNS]

    async def validate(self, tool_name: str, params: Dict[str, Any]) -> ValidationResult:
        """Validate security aspects of the tool call."""
        # Check all string parameters for dangerous patterns
        for param_name, param_value in params.items():
            if isinstance(param_value, str):
                for pattern in self.patterns:
                    if pattern.search(param_value):
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"Security Error: Dangerous pattern detected in parameter '{param_name}': {param_value[:100]}..."
                        )

        return ValidationResult(is_valid=True)


class SafetyValidator(Validator):
    """Validates safety aspects of tool calls."""

    def __init__(self):
        self.forbidden_paths = [
            "C:\\Windows",
            "C:\\Program Files",
            "/etc",
            "/bin",
            "/sbin",
            "/usr/bin",
            "/usr/sbin",
        ]

    async def validate(self, tool_name: str, params: Dict[str, Any]) -> ValidationResult:
        """Validate safety aspects of the tool call."""
        for param_name, param_value in params.items():
            if isinstance(param_value, str):
                # Check for forbidden paths
                for path in self.forbidden_paths:
                    if path.lower() in param_value.lower():
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"Safety Error: Access to system path '{path}' is not allowed in parameter '{param_name}'"
                        )

                # Check for path traversal
                if '../' in param_value or '..\\' in param_value:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Safety Error: Path traversal detected in parameter '{param_name}': {param_value}"
                    )

        return ValidationResult(is_valid=True)


class BusinessRuleValidator(Validator):
    """Validates business rules for specific tools."""

    def __init__(self):
        # Define business rules for different tools
        self.rules = {
            "file_editor": self._validate_file_editor,
            "bash": self._validate_bash,
            "python_execute": self._validate_python_execute,
            "web_search": self._validate_web_search,
        }

    async def validate(self, tool_name: str, params: Dict[str, Any]) -> ValidationResult:
        """Validate business rules for the specific tool."""
        if tool_name in self.rules:
            return await self.rules[tool_name](params)
        return ValidationResult(is_valid=True)

    async def _validate_file_editor(self, params: Dict[str, Any]) -> ValidationResult:
        """Validate file editor parameters."""
        if "file_path" in params:
            file_path = params["file_path"]
            if not isinstance(file_path, str):
                return ValidationResult(
                    is_valid=False,
                    error_message="Business Rule Error: file_path must be a string"
                )

            # Check for forbidden extensions
            forbidden_extensions = [".exe", ".bat", ".cmd", ".com", ".scr", ".vbs", ".js", ".jar"]
            for ext in forbidden_extensions:
                if file_path.lower().endswith(ext):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Business Rule Error: Editing executable files ({ext}) is not allowed"
                    )

        return ValidationResult(is_valid=True)

    async def _validate_bash(self, params: Dict[str, Any]) -> ValidationResult:
        """Validate bash tool parameters."""
        if "command" in params:
            command = params["command"]
            if not isinstance(command, str):
                return ValidationResult(
                    is_valid=False,
                    error_message="Business Rule Error: command must be a string"
                )

            # Check command length
            if len(command) > 10000:  # Arbitrary limit
                return ValidationResult(
                    is_valid=False,
                    error_message="Business Rule Error: Command exceeds maximum length of 10000 characters"
                )

        return ValidationResult(is_valid=True)

    async def _validate_python_execute(self, params: Dict[str, Any]) -> ValidationResult:
        """Validate python execute tool parameters."""
        if "code" in params:
            code = params["code"]
            if not isinstance(code, str):
                return ValidationResult(
                    is_valid=False,
                    error_message="Business Rule Error: code must be a string"
                )

            # Check for dangerous imports
            dangerous_imports = [
                "import os", "import sys", "import subprocess", "import shutil",
                "import socket", "import urllib", "import requests",
                "__import__('os')", "__import__('sys')"
            ]

            code_lower = code.lower()
            for imp in dangerous_imports:
                if imp in code_lower:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Business Rule Error: Dangerous import detected: {imp}"
                    )

        return ValidationResult(is_valid=True)

    async def _validate_web_search(self, params: Dict[str, Any]) -> ValidationResult:
        """Validate web search tool parameters."""
        if "query" in params:
            query = params["query"]
            if not isinstance(query, str):
                return ValidationResult(
                    is_valid=False,
                    error_message="Business Rule Error: query must be a string"
                )

            # Check query length
            if len(query) > 1000:  # Arbitrary limit
                return ValidationResult(
                    is_valid=False,
                    error_message="Business Rule Error: Search query exceeds maximum length of 1000 characters"
                )

        return ValidationResult(is_valid=True)


class ValidationPipeline:
    """Coordinates multiple validators in a pipeline."""

    def __init__(self, validators: List[Validator]):
        self.validators = validators

    async def validate(self, tool_name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
        """Run all validators in sequence."""
        for validator in self.validators:
            result = await validator.validate(tool_name, params)
            if not result.is_valid:
                logger.warning(f"Validation failed for tool '{tool_name}': {result.error_message}")
                return False, result.error_message

        logger.debug(f"All validations passed for tool '{tool_name}'")
        return True, ""


# Global validation pipeline instance
_validation_pipeline: Optional[ValidationPipeline] = None


def get_validation_pipeline() -> ValidationPipeline:
    """Get the global validation pipeline instance."""
    global _validation_pipeline
    if _validation_pipeline is None:
        _validation_pipeline = ValidationPipeline([
            SecurityValidator(),
            SafetyValidator(),
            BusinessRuleValidator(),
        ])
    return _validation_pipeline


async def validate_tool_call(tool_name: str, params: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate a tool call using the standard pipeline."""
    pipeline = get_validation_pipeline()
    return await pipeline.validate(tool_name, params)