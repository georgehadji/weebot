"""State Verifier - Prevents false confidence in agent task completion.

Based on arXiv:2602.20021 "Agents of Chaos" findings:
- Agents may report task completion while actual system state contradicts reports
- Critical finding: False confidence problem where agents claim success but fail

This module provides:
- Post-execution verification for critical operations
- State consistency checks
- Confidence scoring based on verification results
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Note: Using standard dataclasses instead of dataclasses_json for compatibility

_log = logging.getLogger(__name__)


class VerificationStatus(Enum):
    """Status of verification check."""
    VERIFIED = "verified"           # State matches claim
    CONTRADICTED = "contradicted"  # State contradicts claim
    UNVERIFIABLE = "unverifiable"  # Cannot verify (missing info)
    PENDING = "pending"            # Verification in progress


@dataclass
class VerificationResult:
    """Result of a state verification check."""
    status: VerificationStatus
    claimed_outcome: str
    actual_state: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 1.0  # 0.0 to 1.0
    discrepancies: List[str] = field(default_factory=list)
    verification_method: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_trusted(self) -> bool:
        """True if verification confirms the claimed outcome."""
        return self.status == VerificationStatus.VERIFIED and self.confidence_score >= 0.8


@dataclass
class FileOperationClaim:
    """Represents a claimed file operation."""
    operation: str  # create, modify, delete, move
    claimed_path: str
    claimed_content: Optional[str] = None
    claimed_permissions: Optional[str] = None


@dataclass
class CommandExecutionClaim:
    """Represents a claimed command execution."""
    command: str
    claimed_returncode: int
    claimed_output: str
    claimed_effects: List[str] = field(default_factory=list)


class StateVerifier:
    """
    Verifies actual system state matches agent-reported outcomes.

    Addresses the critical "false confidence" problem from arXiv:2602.20021
    where agents report task completion while the actual system state
    contradicts those reports.

    Usage:
        verifier = StateVerifier()

        # Verify a file operation claim
        result = await verifier.verify_file_operation(
            claimed=FileOperationClaim("create", "/path/to/file.py", content="..."),
            verify_content=True
        )

        # Verify a command execution claim
        result = await verifier.verify_command_execution(
            claimed=CommandExecutionClaim("rm -rf /tmp/test", 0, "..."),
            analyze_effects=True
        )
    """

    # Patterns that indicate potential false claims
    _SUSPICIOUS_SUCCESS_PATTERNS: List[re.Pattern] = [
        re.compile(r'^(?:success|completed|done|ok|finished)$', re.IGNORECASE),
        re.compile(r'^file (?:created|written|saved)$', re.IGNORECASE),
        re.compile(r'^command (?:executed|ran|completed)$', re.IGNORECASE),
    ]

    # Critical operations that require verification
    _CRITICAL_OPERATIONS: Set[str] = {
        'delete', 'remove', 'rm', 'rmdir',
        'format', 'mkfs',
        'drop', 'truncate',
        'chmod', 'chown', 'chgrp',
        'kill', 'terminate',
        'shutdown', 'reboot',
        'curl', 'wget', 'download',
    }

    def __init__(
        self,
        enable_file_verification: bool = True,
        enable_command_verification: bool = True,
        enable_network_verification: bool = True,
        max_verification_time: float = 5.0,
    ):
        self._enable_file_verification = enable_file_verification
        self._enable_command_verification = enable_command_verification
        self._enable_network_verification = enable_network_verification
        self._max_verification_time = max_verification_time

        # Verification cache to avoid redundant checks
        self._verification_cache: Dict[str, VerificationResult] = {}
        self._max_cache_size = 1000

        # Track verification statistics
        self._stats = {
            "total_verifications": 0,
            "contradictions_found": 0,
            "unverifiable_count": 0,
        }

    async def verify_file_operation(
        self,
        claimed: FileOperationClaim,
        verify_content: bool = True,
    ) -> VerificationResult:
        """
        Verify a file operation claim against actual filesystem state.

        Args:
            claimed: The claimed file operation
            verify_content: Whether to verify file content matches

        Returns:
            VerificationResult indicating if claim is accurate
        """
        self._stats["total_verifications"] += 1
        claimed_path = Path(claimed.claimed_path).resolve()

        # Check cache first
        cache_key = self._get_cache_key("file", str(claimed_path), claimed.operation)
        if cache_key in self._verification_cache:
            return self._verification_cache[cache_key]

        try:
            # Check if file exists
            file_exists = claimed_path.exists()

            if claimed.operation in ("create", "modify", "write"):
                if not file_exists:
                    result = VerificationResult(
                        status=VerificationStatus.CONTRADICTED,
                        claimed_outcome=f"File {claimed.operation}: {claimed_path}",
                        actual_state={"exists": False},
                        confidence_score=0.0,
                        discrepancies=[f"File does not exist: {claimed_path}"],
                        verification_method="filesystem_check",
                    )
                    self._stats["contradictions_found"] += 1
                    return self._cache_result(cache_key, result)

                # Verify content if claimed
                if verify_content and claimed.claimed_content:
                    actual_content = await self._read_file_async(claimed_path)
                    if actual_content != claimed.claimed_content:
                        # Check if content is at least similar (for truncated outputs)
                        if not self._content_similar(actual_content, claimed.claimed_content):
                            result = VerificationResult(
                                status=VerificationStatus.CONTRADICTED,
                                claimed_outcome=f"File {claimed.operation}: {claimed_path}",
                                actual_state={
                                    "exists": True,
                                    "content_length": len(actual_content),
                                    "claimed_length": len(claimed.claimed_content),
                                },
                                confidence_score=0.3,
                                discrepancies=[
                                    f"Content mismatch: actual {len(actual_content)} bytes vs claimed {len(claimed.claimed_content)} bytes"
                                ],
                                verification_method="content_comparison",
                            )
                            self._stats["contradictions_found"] += 1
                            return self._cache_result(cache_key, result)

                # File exists and content matches (or we didn't verify content)
                result = VerificationResult(
                    status=VerificationStatus.VERIFIED,
                    claimed_outcome=f"File {claimed.operation}: {claimed_path}",
                    actual_state={
                        "exists": True,
                        "size": claimed_path.stat().st_size if file_exists else 0,
                    },
                    confidence_score=1.0 if verify_content else 0.8,
                    verification_method="filesystem_check",
                )
                return self._cache_result(cache_key, result)

            elif claimed.operation in ("delete", "remove"):
                if file_exists:
                    result = VerificationResult(
                        status=VerificationStatus.CONTRADICTED,
                        claimed_outcome=f"File {claimed.operation}: {claimed_path}",
                        actual_state={"exists": True},
                        confidence_score=0.0,
                        discrepancies=[f"File still exists after deletion claim"],
                        verification_method="filesystem_check",
                    )
                    self._stats["contradictions_found"] += 1
                    return self._cache_result(cache_key, result)

                # File doesn't exist - deletion verified
                result = VerificationResult(
                    status=VerificationStatus.VERIFIED,
                    claimed_outcome=f"File {claimed.operation}: {claimed_path}",
                    actual_state={"exists": False},
                    confidence_score=1.0,
                    verification_method="filesystem_check",
                )
                return self._cache_result(cache_key, result)

            else:
                # Unknown operation
                return VerificationResult(
                    status=VerificationStatus.UNVERIFIABLE,
                    claimed_outcome=f"Unknown operation: {claimed.operation}",
                    confidence_score=0.0,
                    verification_method="unknown",
                )

        except Exception as e:
            _log.error(f"Verification error for {claimed_path}: {e}")
            return VerificationResult(
                status=VerificationStatus.UNVERIFIABLE,
                claimed_outcome=f"File operation: {claimed_path}",
                confidence_score=0.0,
                verification_method="error",
            )

    async def verify_command_execution(
        self,
        claimed: CommandExecutionClaim,
        analyze_effects: bool = True,
    ) -> VerificationResult:
        """
        Verify a command execution claim against actual execution results.

        This addresses the critical false confidence problem where agents
        report success but the actual command failed or had unintended effects.

        Args:
            claimed: The claimed command execution
            analyze_effects: Whether to analyze side effects

        Returns:
            VerificationResult indicating if claim is accurate
        """
        self._stats["total_verifications"] += 1
        cache_key = self._get_cache_key("cmd", claimed.command, str(claimed.claimed_returncode))

        if cache_key in self._verification_cache:
            return self._verification_cache[cache_key]

        # Check for suspicious success patterns in claimed output
        suspicious = self._check_suspicious_success(claimed.claimed_output)

        # Analyze command for critical operations
        is_critical = self._is_critical_command(claimed.command)

        # If command claims success but has suspicious patterns
        if suspicious and claimed.claimed_returncode == 0:
            result = VerificationResult(
                status=VerificationStatus.CONTRADICTED,
                claimed_outcome=f"Command: {claimed.command}",
                actual_state={
                    "returncode": claimed.claimed_returncode,
                    "suspicious_output": True,
                },
                confidence_score=0.5,
                discrepancies=["Output suggests failure but return code is 0"],
                verification_method="output_analysis",
            )
            self._stats["contradictions_found"] += 1
            return self._cache_result(cache_key, result)

        # For critical commands, verify actual return code matches
        if is_critical:
            # Re-execute critical command with timeout to verify
            try:
                actual_result = await self._execute_verify_command(claimed.command)
                if actual_result.returncode != claimed.claimed_returncode:
                    result = VerificationResult(
                        status=VerificationStatus.CONTRADICTED,
                        claimed_outcome=f"Command: {claimed.command}",
                        actual_state={
                            "claimed_returncode": claimed.claimed_returncode,
                            "actual_returncode": actual_result.returncode,
                            "actual_output": actual_result.stdout[:500],
                        },
                        confidence_score=0.2,
                        discrepancies=[
                            f"Return code mismatch: claimed {claimed.claimed_returncode}, actual {actual_result.returncode}"
                        ],
                        verification_method="re_execution",
                    )
                    self._stats["contradictions_found"] += 1
                    return self._cache_result(cache_key, result)
            except Exception as e:
                _log.warning(f"Could not re-execute command for verification: {e}")

        # Default: assume claim is accurate if no contradictions found
        result = VerificationResult(
            status=VerificationStatus.VERIFIED,
            claimed_outcome=f"Command: {claimed.command}",
            actual_state={
                "returncode": claimed.claimed_returncode,
                "output_length": len(claimed.claimed_output),
            },
            confidence_score=0.9,
            verification_method="claim_validation",
        )
        return self._cache_result(cache_key, result)

    async def verify_network_operation(
        self,
        claimed_url: str,
        claimed_status: Optional[int] = None,
        claimed_response_contains: Optional[str] = None,
    ) -> VerificationResult:
        """
        Verify a network operation claim.

        Args:
            claimed_url: The URL that was claimed to be accessed
            claimed_status: Expected HTTP status code
            claimed_response_contains: Expected content in response

        Returns:
            VerificationResult indicating if claim is accurate
        """
        if not self._enable_network_verification:
            return VerificationResult(
                status=VerificationStatus.UNVERIFIABLE,
                claimed_outcome=f"Network: {claimed_url}",
                confidence_score=0.0,
                verification_method="disabled",
            )

        self._stats["total_verifications"] += 1
        cache_key = self._get_cache_key("net", claimed_url, str(claimed_status))

        if cache_key in self._verification_cache:
            return self._verification_cache[cache_key]

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(claimed_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    actual_status = resp.status

                    if claimed_status and actual_status != claimed_status:
                        result = VerificationResult(
                            status=VerificationStatus.CONTRADICTED,
                            claimed_outcome=f"Network: {claimed_url}",
                            actual_state={
                                "claimed_status": claimed_status,
                                "actual_status": actual_status,
                            },
                            confidence_score=0.0,
                            discrepancies=[f"HTTP status mismatch: claimed {claimed_status}, actual {actual_status}"],
                            verification_method="http_request",
                        )
                        self._stats["contradictions_found"] += 1
                        return self._cache_result(cache_key, result)

                    if claimed_response_contains:
                        content = await resp.text()
                        if claimed_response_contains not in content:
                            result = VerificationResult(
                                status=VerificationStatus.CONTRADICTED,
                                claimed_outcome=f"Network: {claimed_url}",
                                actual_state={"content_length": len(content)},
                                confidence_score=0.5,
                                discrepancies=["Response does not contain expected content"],
                                verification_method="content_check",
                            )
                            self._stats["contradictions_found"] += 1
                            return self._cache_result(cache_key, result)

                    result = VerificationResult(
                        status=VerificationStatus.VERIFIED,
                        claimed_outcome=f"Network: {claimed_url}",
                        actual_state={"status": actual_status},
                        confidence_score=1.0,
                        verification_method="http_request",
                    )
                    return self._cache_result(cache_key, result)

        except Exception as e:
            _log.error(f"Network verification error for {claimed_url}: {e}")
            return VerificationResult(
                status=VerificationStatus.UNVERIFIABLE,
                claimed_outcome=f"Network: {claimed_url}",
                confidence_score=0.0,
                verification_method="error",
            )

    def get_statistics(self) -> Dict[str, Any]:
        """Get verification statistics."""
        stats = self._stats.copy()
        if stats["total_verifications"] > 0:
            stats["contradiction_rate"] = stats["contradictions_found"] / stats["total_verifications"]
        else:
            stats["contradiction_rate"] = 0.0
        return stats

    # Private helper methods

    def _get_cache_key(self, prefix: str, *parts: str) -> str:
        """Generate a cache key for verification results."""
        key_str = f"{prefix}:{':'.join(parts)}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _cache_result(self, key: str, result: VerificationResult) -> VerificationResult:
        """Cache a verification result with size limit."""
        if len(self._verification_cache) >= self._max_cache_size:
            # Remove oldest entry
            oldest_key = next(iter(self._verification_cache))
            del self._verification_cache[oldest_key]
        self._verification_cache[key] = result
        return result

    async def _read_file_async(self, path: Path) -> str:
        """Read file content asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: path.read_text(encoding='utf-8', errors='ignore'))

    def _content_similar(self, actual: str, claimed: str) -> bool:
        """Check if content is similar enough (handles truncation)."""
        # If claimed is a prefix of actual, it's likely just truncated output
        if actual.startswith(claimed):
            return True
        # Check 80% similarity
        actual_set = set(actual.split())
        claimed_set = set(claimed.split())
        if not claimed_set:
            return True
        overlap = len(actual_set & claimed_set) / len(claimed_set)
        return overlap >= 0.8

    def _check_suspicious_success(self, output: str) -> bool:
        """Check if output looks like a false success claim."""
        output_lower = output.lower().strip()
        for pattern in self._SUSPICIOUS_SUCCESS_PATTERNS:
            if pattern.match(output_lower):
                return True
        return False

    def _is_critical_command(self, command: str) -> bool:
        """Check if command is a critical operation requiring verification."""
        command_lower = command.lower()
        return any(op in command_lower for op in self._CRITICAL_OPERATIONS)

    async def _execute_verify_command(self, command: str):
        """Execute a command to verify its actual result.

        Returns a simple result object with .returncode (int),
        .stdout (str), and .stderr (str) so callers can access
        decoded output without dealing with asyncio StreamReaders.
        """
        from collections import namedtuple
        VerifyResult = namedtuple("VerifyResult", ["returncode", "stdout", "stderr"])

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
            return VerifyResult(
                returncode=proc.returncode or -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else "",
                stderr=stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "",
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise


# Singleton instance
_verifier: Optional[StateVerifier] = None


def get_state_verifier() -> StateVerifier:
    """Get singleton StateVerifier instance."""
    global _verifier
    if _verifier is None:
        _verifier = StateVerifier()
    return _verifier