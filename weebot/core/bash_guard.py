"""Bash command safety guardrails.

This module provides pattern-based safety checking for shell commands
executed by the agent, preventing destructive operations and
requiring approval for risky commands.

Based on patterns from The Dev Squad analysis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

# Optional global hook registry for post_bash_guard events.
_bash_guard_hooks: Any = None


def set_bash_guard_hooks(registry: Any) -> None:
    global _bash_guard_hooks
    _bash_guard_hooks = registry


class RiskLevel(str, Enum):
    """Risk level for a shell command."""

    SAFE = "safe"  # No risk, auto-approve
    SUSPICIOUS = "suspicious"  # Check carefully, suggest approval
    DANGEROUS = "dangerous"  # High risk, require explicit approval
    BLOCKED = "blocked"  # Never allow, will not execute


@dataclass(frozen=True)
class SafetyCheck:
    """A safety check result for a specific pattern match."""

    pattern: str  # The regex pattern that matched
    risk_level: RiskLevel
    description: str  # Human-readable description of the risk
    suggestion: str  # What the user should do instead


class BashGuard:
    """Evaluates shell commands for safety.

    This class uses pattern matching to identify potentially dangerous
    commands and assign appropriate risk levels. It covers:
    - Destructive operations (deletions, overwrites)
    - System mutations (services, permissions, registry)
    - Credential exposure (hardcoded secrets)
    - Network risks (piping from internet)
    - Resource exhaustion (fork bombs, unbounded operations)

    Example:
        >>> guard = BashGuard()
        >>> risk, checks = guard.evaluate("rm -rf /")
        >>> risk
        <RiskLevel.BLOCKED: 'blocked'>
        >>> guard.is_safe("echo hello")
        True
    """

    # Destructive file operations
    DESTRUCTIVE_PATTERNS: list[tuple[str, RiskLevel, str, str]] = [
        (
            r"rm\s+-rf?\s*/\s*$",
            RiskLevel.BLOCKED,
            "Attempting to delete root directory",
            "This would destroy your entire system. Use specific file paths instead.",
        ),
        (
            r"rm\s+-rf?\s*/\s+",
            RiskLevel.BLOCKED,
            "Recursive deletion of system directories",
            "This would delete system files. Use specific file paths instead.",
        ),
        (
            r"rm\s+-rf?\s+/(bin|sbin|boot|dev|etc|lib|proc|root|sys|usr|var)\b",
            RiskLevel.BLOCKED,
            "Attempting to delete critical system directory",
            "This would break your system. Use package manager to remove software.",
        ),
        (
            r"rm\s+-rf?\s+~/?\*$",
            RiskLevel.DANGEROUS,
            "Deleting all files in home directory",
            "Use specific file paths instead of wildcards in home directory.",
        ),
        (
            r"rm\s+-rf?\s+\.",
            RiskLevel.DANGEROUS,
            "Recursive deletion with relative path",
            "Verify the current directory is correct. Consider using absolute paths.",
        ),
        (
            r">\s*/(etc|bin|sbin|boot|dev|lib|proc|root|sys|usr|var|opt|srv)/",
            RiskLevel.SUSPICIOUS,
            "Redirect overwriting a system directory file",
            "Ensure you're not overwriting critical system files.",
        ),
        (
            r"mv\s+.*\s+/dev/null",
            RiskLevel.SUSPICIOUS,
            "Moving files to /dev/null (deletion)",
            "Use 'rm' explicitly if you want to delete files.",
        ),
    ]

    # System mutation operations
    SYSTEM_PATTERNS: list[tuple[str, RiskLevel, str, str]] = [
        (
            r"\bsystemctl\s+(stop|restart|disable|mask)\b",
            RiskLevel.DANGEROUS,
            "Service management operation",
            "Stopping critical services may affect system stability. Verify the service name.",
        ),
        (
            r"\bservice\s+\w+\s+(stop|restart)",
            RiskLevel.DANGEROUS,
            "Service management via service command",
            "Verify this is not a critical system service.",
        ),
        (
            r"\bchmod\s+-?R?\s+777\b",
            RiskLevel.DANGEROUS,
            "Overly permissive permissions (world-writable)",
            "Use more restrictive permissions (e.g., 755 for directories, 644 for files).",
        ),
        (
            r"\bchown\s+-R\s+(root|0)",
            RiskLevel.DANGEROUS,
            "Changing ownership to root recursively",
            "This may break file access. Ensure you have a backup.",
        ),
        (
            r"\bmkfs\.",
            RiskLevel.BLOCKED,
            "Filesystem creation/formatting",
            "This erases all data on the target device. Use disk management tools instead.",
        ),
        (
            r"\b(dd|fallocate)\s+.*\b(of|if)=",
            RiskLevel.DANGEROUS,
            "Direct disk writing",
            "This can overwrite partition tables or filesystems. Double-check target device.",
        ),
        (
            r"\breg\s+add\b",
            RiskLevel.DANGEROUS,
            "Windows registry modification",
            "Registry changes can destabilize Windows. Create a backup first.",
        ),
        (
            r"\breg\s+delete\b",
            RiskLevel.BLOCKED,
            "Windows registry deletion",
            "This can break Windows installation. Use Control Panel instead.",
        ),
        (
            r"\bformat\s+[a-zA-Z]:",
            RiskLevel.BLOCKED,
            "Disk format (Windows)",
            "This erases all data on the drive. Use Windows Explorer to format.",
        ),
    ]

    # Credential and secret exposure
    CREDENTIAL_PATTERNS: list[tuple[str, RiskLevel, str, str]] = [
        (
            r"\b(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]",
            RiskLevel.SUSPICIOUS,
            "Potential hardcoded password",
            "Use environment variables or a secrets manager instead.",
        ),
        (
            r"\b(api[_-]?key|apikey)\s*=\s*['\"][a-zA-Z0-9_\-]{16,}['\"]",
            RiskLevel.SUSPICIOUS,
            "Potential hardcoded API key",
            "Use environment variables or a secrets manager.",
        ),
        (
            r"\b(secret|token)\s*=\s*['\"][a-zA-Z0-9_\-]{20,}['\"]",
            RiskLevel.SUSPICIOUS,
            "Potential hardcoded secret/token",
            "Use environment variables or a secrets manager.",
        ),
        (
            r"AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)",
            RiskLevel.SUSPICIOUS,
            "AWS credentials in command",
            "Use IAM roles or AWS CLI configuration files instead.",
        ),
        (
            r"(GITHUB|GITLAB)_TOKEN",
            RiskLevel.SUSPICIOUS,
            "Version control token in command",
            "Use environment variables or credential helpers.",
        ),
    ]

    # Network and download risks
    NETWORK_PATTERNS: list[tuple[str, RiskLevel, str, str]] = [
        (
            r"\bcurl\s+.*\|\s*(bash|sh|zsh|fish)",
            RiskLevel.DANGEROUS,
            "Piping curl output directly to shell",
            "Download the script first, review it, then execute. This prevents supply chain attacks.",
        ),
        (
            r"\bwget\s+.*(-O|-)\s*.*\|\s*(bash|sh|zsh|fish)",
            RiskLevel.DANGEROUS,
            "Piping wget output directly to shell",
            "Download the script first, review it, then execute.",
        ),
        (
            r"\b(fetch|curl|wget)\s+.*\|\s*(bash|sh|zsh|fish)",
            RiskLevel.DANGEROUS,
            "Piping downloaded content to shell",
            "Review the script before execution to prevent malware.",
        ),
        (
            r"\bnc\s+(-[lL]|--listen)",
            RiskLevel.SUSPICIOUS,
            "Netcat listener (network service)",
            "Ensure this is intentional and properly firewalled.",
        ),
        (
            r"\bpython\s+-m\s+http\.server",
            RiskLevel.SUSPICIOUS,
            "HTTP server exposes files",
            "Verify you're not exposing sensitive files on the network.",
        ),
        (
            r"\b(ssh|scp|sftp)\s+.*\s*password\s*=",
            RiskLevel.SUSPICIOUS,
            "SSH with password in command",
            "Use SSH keys instead of passwords in commands.",
        ),
    ]

    # Resource exhaustion and attacks
    ATTACK_PATTERNS: list[tuple[str, RiskLevel, str, str]] = [
        (
            r":\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\};\s*:",
            RiskLevel.BLOCKED,
            "Fork bomb detected",
            "This crashes the system by exhausting process limits.",
        ),
        (
            r"\bbash\s+-c\s+['\"].*:.*\|\s*bash['\"]",
            RiskLevel.SUSPICIOUS,
            "Self-replicating bash command",
            "Verify this is not a fork bomb or resource exhaustion attack.",
        ),
        (
            r"\bwhile\s+true\s*;\s*do.*done",
            RiskLevel.SUSPICIOUS,
            "Infinite loop",
            "Ensure this loop has a proper termination condition.",
        ),
        (
            r"\bfor\s+\(\s*;\s*;\s*\)",
            RiskLevel.SUSPICIOUS,
            "C-style infinite loop",
            "Ensure this loop has a proper termination condition.",
        ),
        (
            r"\b__import__\s*\(.+\)\s*\.\s*system\b",
            RiskLevel.DANGEROUS,
            "Obfuscated Python system call",
            "Use safe alternatives. This bypasses standard import detection.",
        ),
        (
            r"\bgetattr\s*\(\s*__import__\s*\(.+\)\s*,\s*['\"](system|popen)['\"]\s*\)",
            RiskLevel.DANGEROUS,
            "Obfuscated Python dynamic call",
            "Indirect system calls via getattr/__import__ are prohibited.",
        ),
    ]

    # Windows-specific risks
    WINDOWS_PATTERNS: list[tuple[str, RiskLevel, str, str]] = [
        (
            r"\bdel\s+/[fFqQs]",
            RiskLevel.DANGEROUS,
            "Force deletion with quiet mode (Windows)",
            "Quiet deletion prevents confirmation. Verify target paths.",
        ),
        (
            r"\brd\s+/[sSqQ]",
            RiskLevel.DANGEROUS,
            "Recursive directory removal (Windows)",
            "This deletes directories and contents. Verify the path.",
        ),
        (
            r"\bcd\s+\\",
            RiskLevel.SUSPICIOUS,
            "Changing to root directory (Windows)",
            "Ensure subsequent operations don't affect system files.",
        ),
    ]

    def __init__(self, custom_patterns: Optional[list[tuple[str, RiskLevel, str, str]]] = None):
        """Initialize the BashGuard.

        Args:
            custom_patterns: Optional list of custom patterns to add
        """
        self._all_patterns: list[tuple[str, RiskLevel, str, str]] = []
        self._all_patterns.extend(self.DESTRUCTIVE_PATTERNS)
        self._all_patterns.extend(self.SYSTEM_PATTERNS)
        self._all_patterns.extend(self.CREDENTIAL_PATTERNS)
        self._all_patterns.extend(self.NETWORK_PATTERNS)
        self._all_patterns.extend(self.ATTACK_PATTERNS)
        self._all_patterns.extend(self.WINDOWS_PATTERNS)

        if custom_patterns:
            self._all_patterns.extend(custom_patterns)

        # Compile patterns for performance
        self._compiled_patterns: list[tuple[re.Pattern, RiskLevel, str, str]] = []
        for pattern, risk, desc, suggestion in self._all_patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append((compiled, risk, desc, suggestion))
            except re.error:
                # Skip invalid patterns
                continue

    def evaluate(self, command: str) -> tuple[RiskLevel, list[SafetyCheck]]:
        """Evaluate a command for safety.

        Args:
            command: The shell command to evaluate

        Returns:
            Tuple of (highest_risk_level, list_of_all_checks)
            The highest_risk_level is the most severe risk found.
        """
        if not command or not command.strip():
            return RiskLevel.SAFE, []

        command = command.strip()
        checks: list[SafetyCheck] = []
        max_risk = RiskLevel.SAFE

        for compiled_pattern, risk, desc, suggestion in self._compiled_patterns:
            if compiled_pattern.search(command):
                check = SafetyCheck(
                    pattern=compiled_pattern.pattern,
                    risk_level=risk,
                    description=desc,
                    suggestion=suggestion,
                )
                checks.append(check)

                # Update max risk
                risk_order = [RiskLevel.SAFE, RiskLevel.SUSPICIOUS, RiskLevel.DANGEROUS, RiskLevel.BLOCKED]
                if risk_order.index(risk) > risk_order.index(max_risk):
                    max_risk = risk

        # Emit Prometheus counter for security events (best-effort).
        if max_risk != RiskLevel.SAFE:
            try:
                from weebot.infrastructure.observability import metrics as _m
                _m.bash_guard_events_total.labels(
                    risk_level=max_risk.value
                ).inc()
            except Exception:
                pass  # metrics are best-effort — never break security evaluation

        return max_risk, checks

    def is_safe(self, command: str) -> bool:
        """Quick check if command is safe (no approval needed).

        Args:
            command: The shell command to check

        Returns:
            True if command is SAFE (no risks detected)
        """
        risk, _ = self.evaluate(command)
        return risk == RiskLevel.SAFE

    def is_blocked(self, command: str) -> bool:
        """Check if command is blocked (will never execute).

        Args:
            command: The shell command to check

        Returns:
            True if command is BLOCKED
        """
        risk, _ = self.evaluate(command)
        return risk == RiskLevel.BLOCKED

    def requires_approval(self, command: str) -> bool:
        """Check if command requires user approval.

        Args:
            command: The shell command to check

        Returns:
            True if command is SUSPICIOUS or DANGEROUS
        """
        risk, _ = self.evaluate(command)
        return risk in (RiskLevel.SUSPICIOUS, RiskLevel.DANGEROUS)

    def get_risk_description(self, risk: RiskLevel) -> str:
        """Get human-readable risk description.

        Args:
            risk: The risk level

        Returns:
            Human-readable description
        """
        descriptions = {
            RiskLevel.SAFE: "No known risks detected. Command can proceed automatically.",
            RiskLevel.SUSPICIOUS: "Potential risk detected. Review recommended before proceeding.",
            RiskLevel.DANGEROUS: "High risk operation. Explicit approval required.",
            RiskLevel.BLOCKED: "Command blocked for safety. Will not execute.",
        }
        return descriptions.get(risk, "Unknown risk level")

    def format_check_results(self, checks: list[SafetyCheck]) -> str:
        """Format safety checks for display.

        Args:
            checks: List of safety checks

        Returns:
            Formatted string suitable for CLI display
        """
        if not checks:
            return "No safety issues detected."

        lines = ["Safety Check Results:", ""]
        for i, check in enumerate(checks, 1):
            emoji = {"safe": "✓", "suspicious": "⚠", "dangerous": "▲", "blocked": "✗"}.get(
                check.risk_level.value, "?"
            )
            lines.append(f"{i}. [{emoji}] {check.risk_level.value.upper()}: {check.description}")
            lines.append(f"   Suggestion: {check.suggestion}")
            lines.append("")

        return "\n".join(lines)
