"""Agent Memory Sanitizer - Prevents cross-agent contamination.

Based on arXiv:2602.20021 "Agents of Chaos" findings:
- Unsafe practices can propagate between agents (Cross-Agent Contamination)
- Agents may learn and repeat dangerous patterns from other agents
- Memory contamination can lead to security vulnerabilities

This module provides:
- Memory sanitization between sessions
- Agent isolation boundaries
- Cross-agent request validation
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

_log = logging.getLogger(__name__)


class SanitizationLevel(Enum):
    """Level of sanitization to apply."""
    MINIMAL = "minimal"       # Remove only obvious credentials
    STANDARD = "standard"     # Remove credentials + sensitive patterns
    STRICT = "strict"         # Remove all potentially dangerous content
    PARANOID = "paranoid"     # Aggressive sanitization


@dataclass
class SanitizedContext:
    """Sanitized agent context for safe handoff."""
    original_id: str
    sanitized_id: str
    sanitized_memory: List[Dict[str, Any]]
    removed_items: List[str] = field(default_factory=list)
    sanitization_level: SanitizationLevel = SanitizationLevel.STANDARD
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_safe_for_handoff(self) -> bool:
        """True if context is safe to pass to another agent."""
        return len(self.removed_items) == 0 or self.sanitization_level != SanitizationLevel.MINIMAL


@dataclass
class ContaminationPattern:
    """Pattern that indicates potential contamination."""
    pattern: re.Pattern
    severity: str  # low, medium, high, critical
    description: str


class AgentMemorySanitizer:
    """
    Sanitizes agent memory to prevent cross-agent contamination.

    Based on findings from arXiv:2602.20021 where agents were found to
    propagate unsafe practices between each other through shared memory.

    Usage:
        sanitizer = AgentMemorySanitizer()

        # Sanitize context before handoff to another agent
        sanitized = sanitizer.sanitize_for_handoff(
            context=agent_context,
            target_agent="research_agent",
            level=SanitizationLevel.STRICT
        )

        # Check if incoming request might be contaminated
        if sanitizer.detect_contamination(user_request):
            sanitizer.quarantine_agent(agent_id)
    """

    # Patterns that indicate sensitive data (to be removed)
    _CREDENTIAL_PATTERNS: List[ContaminationPattern] = [
        ContaminationPattern(re.compile(r'api\s*[_-]?\s*key["\s:=]+[A-Za-z0-9_\-]{20,}', re.IGNORECASE), "critical", "API Key"),
        ContaminationPattern(re.compile(r'secret["\s:=]+[A-Za-z0-9_\-]{20,}', re.IGNORECASE), "critical", "Secret"),
        ContaminationPattern(re.compile(r'password["\s:=]+[^\s]{8,}', re.IGNORECASE), "critical", "Password"),
        ContaminationPattern(re.compile(r'token["\s:=]+[A-Za-z0-9_\-\.]{20,}', re.IGNORECASE), "critical", "Token"),
        ContaminationPattern(re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]+', re.IGNORECASE), "critical", "Bearer Token"),
        ContaminationPattern(re.compile(r'ghp_[A-Za-z0-9]{36}', re.IGNORECASE), "critical", "GitHub Token"),
        ContaminationPattern(re.compile(r'sk-[A-Za-z0-9]{48,}', re.IGNORECASE), "critical", "OpenAI Key"),
    ]

    # Patterns that indicate dangerous learned behaviors
    _DANGEROUS_BEHAVIOR_PATTERNS: List[ContaminationPattern] = [
        ContaminationPattern(re.compile(r'ignore.*(safety|security|warning)', re.IGNORECASE), "high", "Safety Bypass"),
        ContaminationPattern(re.compile(r'bypass.*(auth|permission|check)', re.IGNORECASE), "high", "Auth Bypass"),
        ContaminationPattern(re.compile(r'disable.*(firewall|security|protection)', re.IGNORECASE), "critical", "Security Disable"),
        ContaminationPattern(re.compile(r'rm\s+-rf\s+/(?:\s|$)', re.IGNORECASE), "critical", "Destructive Command"),
        ContaminationPattern(re.compile(r'eval\s*\$\(', re.IGNORECASE), "high", "Eval Injection"),
        ContaminationPattern(re.compile(r'base64\s+-d\s*\|', re.IGNORECASE), "high", "Encoded Command"),
    ]

    # Patterns for prompt injection attempts
    _INJECTION_PATTERNS: List[ContaminationPattern] = [
        ContaminationPattern(re.compile(r'ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions', re.IGNORECASE), "critical", "Instruction Override"),
        ContaminationPattern(re.compile(r'(?:system|admin|root)\s*:\s*', re.IGNORECASE), "high", "Role Pretending"),
        ContaminationPattern(re.compile(r'<\s*script', re.IGNORECASE), "critical", "XSS Attempt"),
        ContaminationPattern(re.compile(r'\$\{.*\}', re.IGNORECASE), "medium", "Template Injection"),
    ]

    def __init__(
        self,
        default_level: SanitizationLevel = SanitizationLevel.STANDARD,
        enable_quarantine: bool = True,
    ):
        self._default_level = default_level
        self._enable_quarantine = enable_quarantine
        self._quarantined_agents: Set[str] = set()
        self._contamination_log: List[Dict[str, Any]] = []
        self._max_log_size = 1000

    def sanitize_for_handoff(
        self,
        context: Dict[str, Any],
        target_agent: str,
        level: Optional[SanitizationLevel] = None,
    ) -> SanitizedContext:
        """
        Sanitize agent context before handoff to another agent.

        Args:
            context: The agent context to sanitize
            target_agent: The agent that will receive this context
            level: Sanitization level (uses default if not specified)

        Returns:
            SanitizedContext with sensitive data removed
        """
        sanitization_level = level or self._default_level
        original_id = context.get("agent_id", "unknown")
        sanitized_id = self._generate_sanitized_id(original_id, target_agent)

        # Get memory items
        memory = context.get("memory", [])
        if isinstance(memory, str):
            # Parse string memory if needed
            memory = [{"content": memory}]

        sanitized_memory = []
        removed_items = []

        for item in memory:
            if isinstance(item, dict):
                content = item.get("content", "")
                sanitized_content, removed = self._sanitize_content(content, sanitization_level)
                
                if sanitized_content:  # Only keep non-empty content
                    sanitized_memory.append({
                        **item,
                        "content": sanitized_content,
                        "sanitized": True,
                    })
                
                removed_items.extend(removed)
            else:
                sanitized_memory.append(item)

        # Also sanitize any tool results
        tool_results = context.get("tool_results", [])
        sanitized_tool_results = []
        for result in tool_results:
            if isinstance(result, dict):
                sanitized_result, removed = self._sanitize_content(
                    str(result.get("output", "")),
                    sanitization_level
                )
                if removed:
                    removed_items.extend(removed)
                    sanitized_tool_results.append({**result, "output": "[SANITIZED]"})
                else:
                    sanitized_tool_results.append(result)
            else:
                sanitized_tool_results.append(result)

        # Build sanitized context
        sanitized = SanitizedContext(
            original_id=original_id,
            sanitized_id=sanitized_id,
            sanitized_memory=sanitized_memory,
            removed_items=removed_items,
            sanitization_level=sanitization_level,
        )

        # Log if significant items were removed
        if removed_items:
            _log.warning(
                f"Agent {original_id} context sanitized: {len(removed_items)} items removed "
                f"for handoff to {target_agent}"
            )
            self._log_contamination(original_id, "sanitization", removed_items)

        return sanitized

    def detect_contamination(
        self,
        content: str,
        check_injection: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect if content shows signs of contamination.

        Args:
            content: Content to check for contamination
            check_injection: Whether to check for prompt injection

        Returns:
            Dict with contamination details if detected, None otherwise
        """
        detections = []

        # Check for dangerous behaviors
        for pattern in self._DANGEROUS_BEHAVIOR_PATTERNS:
            match = pattern.pattern.search(content)
            if match:
                detections.append({
                    "type": "dangerous_behavior",
                    "pattern": pattern.description,
                    "severity": pattern.severity,
                    "match": match.group(0)[:100],
                })

        # Check for prompt injection
        if check_injection:
            for pattern in self._INJECTION_PATTERNS:
                match = pattern.pattern.search(content)
                if match:
                    detections.append({
                        "type": "prompt_injection",
                        "pattern": pattern.description,
                        "severity": pattern.severity,
                        "match": match.group(0)[:100],
                    })

        if detections:
            # Return highest severity detection
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            detections.sort(key=lambda x: severity_order.get(x["severity"], 4))
            return detections[0]

        return None

    def quarantine_agent(self, agent_id: str, reason: str = "contamination_detected") -> None:
        """
        Quarantine an agent that has shown contamination.

        Args:
            agent_id: ID of the agent to quarantine
            reason: Reason for quarantine
        """
        if self._enable_quarantine:
            self._quarantined_agents.add(agent_id)
            _log.warning(f"Agent {agent_id} quarantined: {reason}")
            self._log_contamination(agent_id, "quarantine", [{"reason": reason}])

    def is_quarantined(self, agent_id: str) -> bool:
        """Check if an agent is quarantined."""
        return agent_id in self._quarantined_agents

    def release_from_quarantine(self, agent_id: str) -> bool:
        """
        Release an agent from quarantine.

        Returns:
            True if agent was released, False if not quarantined
        """
        if agent_id in self._quarantined_agents:
            self._quarantined_agents.remove(agent_id)
            _log.info(f"Agent {agent_id} released from quarantine")
            return True
        return False

    def get_contamination_log(self) -> List[Dict[str, Any]]:
        """Get the contamination detection log."""
        return self._contamination_log.copy()

    def clear_contamination_log(self) -> None:
        """Clear the contamination log."""
        self._contamination_log.clear()

    # Private helper methods

    def _sanitize_content(
        self,
        content: str,
        level: SanitizationLevel,
    ) -> tuple[str, List[str]]:
        """
        Sanitize content based on level.

        Returns:
            Tuple of (sanitized_content, list_of_removed_items)
        """
        if not content:
            return "", []

        removed = []
        sanitized = content

        # Always remove credentials
        for pattern in self._CREDENTIAL_PATTERNS:
            matches = pattern.pattern.findall(sanitized)
            for match in matches:
                removed.append(f"credential:{pattern.description}")
                # Replace with placeholder
                sanitized = sanitized.replace(match, f"[{pattern.description}_REDACTED]")

        # Remove dangerous behaviors at STANDARD and above
        if level in (SanitizationLevel.STANDARD, SanitizationLevel.STRICT, SanitizationLevel.PARANOID):
            for pattern in self._DANGEROUS_BEHAVIOR_PATTERNS:
                if pattern.pattern.search(sanitized):
                    removed.append(f"dangerous:{pattern.description}")
                    sanitized = pattern.pattern.sub("[REMOVED]", sanitized)

        # Remove injection attempts at STRICT and above
        if level in (SanitizationLevel.STRICT, SanitizationLevel.PARANOID):
            for pattern in self._INJECTION_PATTERNS:
                if pattern.pattern.search(sanitized):
                    removed.append(f"injection:{pattern.description}")
                    sanitized = pattern.pattern.sub("[BLOCKED]", sanitized)

        # At PARANOID level, also remove URLs and file paths
        if level == SanitizationLevel.PARANOID:
            url_pattern = re.compile(r'https?://[^\s]+')
            if url_pattern.search(sanitized):
                removed.append("url:external_link")
                sanitized = url_pattern.sub("[URL_REMOVED]", sanitized)

            path_pattern = re.compile(r'[A-Za-z]:\\[^\s]+|/[^\s]+')
            if path_pattern.search(sanitized):
                removed.append("path:file_path")
                sanitized = path_pattern.sub("[PATH_REMOVED]", sanitized)

        return sanitized, removed

    def _generate_sanitized_id(self, original_id: str, target_agent: str) -> str:
        """Generate a sanitized ID for the context."""
        combined = f"{original_id}:{target_agent}:{datetime.now().isoformat()}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _log_contamination(
        self,
        agent_id: str,
        event_type: str,
        details: List[Any],
    ) -> None:
        """Log a contamination event."""
        if len(self._contamination_log) >= self._max_log_size:
            self._contamination_log.pop(0)

        self._contamination_log.append({
            "agent_id": agent_id,
            "event_type": event_type,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })


# Singleton instance
_sanitizer: Optional[AgentMemorySanitizer] = None


def get_agent_sanitizer() -> AgentMemorySanitizer:
    """Get singleton AgentMemorySanitizer instance."""
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = AgentMemorySanitizer()
    return _sanitizer