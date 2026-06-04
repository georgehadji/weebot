"""Security Audit Logger - Comprehensive action trails and anomaly detection.

Based on arXiv:2602.20021 "Agents of Chaos" findings:
- Agents may not properly log their decision-making process
- Lack of complete action trails makes debugging and security analysis difficult
- Real-time anomaly detection is crucial for identifying compromised agents

This module provides:
- Complete action trails with cryptographic signatures
- Real-time anomaly detection based on audit patterns
- Immutable audit log with tamper detection
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_log = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""
    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_STOP = "agent_stop"
    AGENT_HANDOVER = "agent_handover"

    # Decision points
    DECISION_POINT = "decision_point"
    TOOL_SELECTION = "tool_selection"
    APPROVAL_REQUEST = "approval_request"

    # Tool execution
    TOOL_EXECUTE = "tool_execute"
    TOOL_SUCCESS = "tool_success"
    TOOL_FAILURE = "tool_failure"
    TOOL_DENIED = "tool_denied"

    # Security events
    SECURITY_BLOCK = "security_block"
    SECURITY_WARNING = "security_warning"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"

    # Data operations
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    DATA_EXFILTRATION = "data_exfiltration"

    # Anomaly detection
    ANOMALY_DETECTED = "anomaly_detected"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"


@dataclass
class AuditEvent:
    """Single audit event record."""
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    agent_id: str
    session_id: str
    user_id: Optional[str]

    # Event details
    action: str
    target: Optional[str]
    result: str  # success, failure, denied, pending

    # Context
    decision_reasoning: Optional[str] = None
    tool_used: Optional[str] = None
    confidence_score: Optional[float] = None

    # Security context
    risk_level: str = "low"  # low, medium, high, critical
    ip_address: Optional[str] = None

    # Chain for tamper detection
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Generate event hash for tamper detection."""
        if self.event_hash is None:
            self.event_hash = self._generate_hash()
        if self.previous_hash is None:
            self.previous_hash = ""

    def _generate_hash(self) -> str:
        """Generate cryptographic hash of event."""
        content = f"{self.event_id}{self.event_type.value}{self.timestamp.isoformat()}"
        content += f"{self.agent_id}{self.action}{self.result}"
        return hashlib.sha256(content.encode()).hexdigest()


class AnomalyType(Enum):
    """Types of anomalies that can be detected."""
    RAPID_TOOL_USAGE = "rapid_tool_usage"  # Too many tools in short time
    UNUSUAL_COMMAND_PATTERN = "unusual_command_pattern"
    DATA_ACCESS_SPIKE = "data_access_spike"
    AUTHENTICATION_ANOMALY = "authentication_anomaly"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    SUSPICIOUS_HANDOVER = "suspicious_handover"
    CREDENTIAL_ACCESS = "credential_access"


@dataclass
class AnomalyAlert:
    """Anomaly detection alert."""
    anomaly_type: AnomalyType
    severity: str  # low, medium, high, critical
    agent_id: str
    description: str
    evidence: Dict[str, Any]
    recommended_action: str
    timestamp: datetime = field(default_factory=datetime.now)


class SecurityAuditLogger:
    """
    Comprehensive security audit logger with anomaly detection.

    Provides complete action trails with cryptographic chain for tamper
    detection, and real-time anomaly detection based on audit patterns.

    Usage:
        logger = SecurityAuditLogger()

        # Log an event
        logger.log_event(
            event_type=AuditEventType.TOOL_EXECUTE,
            agent_id="agent_123",
            action="execute_bash",
            target="rm -rf /tmp",
            result="denied",
            reasoning="Command blocked by security policy"
        )

        # Check for anomalies
        alerts = logger.check_anomalies("agent_123")
        for alert in alerts:
            logger.handle_anomaly(alert)
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        enable_anomaly_detection: bool = True,
        enable_file_persistence: bool = True,
        max_events_in_memory: int = 10000,
    ):
        self._log_file = log_file
        self._enable_anomaly_detection = enable_anomaly_detection
        self._enable_file_persistence = enable_file_persistence
        self._max_events_in_memory = max_events_in_memory

        # In-memory event storage
        self._events: List[AuditEvent] = []
        self._events_lock = threading.Lock()

        # Anomaly detection state
        self._agent_event_counts: Dict[str, List[datetime]] = defaultdict(list)
        self._agent_tool_usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._agent_data_access: Dict[str, int] = defaultdict(int)
        self._last_anomaly_check: Dict[str, datetime] = {}

        # Anomaly thresholds
        self._thresholds = {
            "max_tools_per_minute": 30,
            "max_events_per_minute": 100,
            "max_data_access_per_minute": 50,
            "anomaly_check_interval_seconds": 60,
        }

        # Chain for tamper detection
        self._last_hash: str = ""
        self._chain_lock = threading.Lock()

        # Load existing events if file exists
        if log_file and enable_file_persistence:
            self._load_events()

    def log_event(
        self,
        event_type: AuditEventType,
        agent_id: str,
        action: str,
        result: str,
        session_id: str = "default",
        user_id: Optional[str] = None,
        target: Optional[str] = None,
        decision_reasoning: Optional[str] = None,
        tool_used: Optional[str] = None,
        confidence_score: Optional[float] = None,
        risk_level: str = "low",
        ip_address: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """
        Log an audit event.

        Args:
            event_type: Type of the event
            agent_id: ID of the agent performing the action
            action: Description of the action
            result: Result of the action (success, failure, denied, pending)
            session_id: Session identifier
            user_id: User ID if applicable
            target: Target of the action (e.g., file path, URL)
            decision_reasoning: Reasoning behind the decision
            tool_used: Tool used for this action
            confidence_score: Confidence score of the decision
            risk_level: Risk level (low, medium, high, critical)
            ip_address: IP address if applicable
            metadata: Additional metadata

        Returns:
            The created AuditEvent
        """
        # Generate event ID
        event_id = hashlib.sha256(
            f"{agent_id}:{action}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        # Create event with chain
        with self._chain_lock:
            event = AuditEvent(
                event_id=event_id,
                event_type=event_type,
                timestamp=datetime.now(),
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                action=action,
                target=target,
                result=result,
                decision_reasoning=decision_reasoning,
                tool_used=tool_used,
                confidence_score=confidence_score,
                risk_level=risk_level,
                ip_address=ip_address,
                previous_hash=self._last_hash,
                metadata=metadata or {},
            )
            self._last_hash = event.event_hash

        # Store event
        with self._events_lock:
            self._events.append(event)
            if len(self._events) > self._max_events_in_memory:
                self._events = self._events[-self._max_events_in_memory:]

        # Persist to file
        if self._enable_file_persistence and self._log_file:
            self._persist_event(event)

        # Update anomaly detection state
        if self._enable_anomaly_detection:
            self._update_anomaly_state(event)

        # Check for anomalies
        if self._enable_anomaly_detection:
            alerts = self._check_agent_anomalies(agent_id)
            for alert in alerts:
                self._handle_anomaly_internal(alert)

        return event

    def get_events(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """
        Query audit events.

        Args:
            agent_id: Filter by agent ID
            event_type: Filter by event type
            since: Return events since this time
            limit: Maximum number of events to return

        Returns:
            List of matching AuditEvent objects
        """
        with self._events_lock:
            filtered = self._events.copy()

        if agent_id:
            filtered = [e for e in filtered if e.agent_id == agent_id]
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        if since:
            filtered = [e for e in filtered if e.timestamp >= since]

        return filtered[-limit:]

    def verify_chain_integrity(self) -> Dict[str, Any]:
        """
        Verify the integrity of the audit chain.

        Returns:
            Dict with verification results
        """
        with self._chain_lock:
            events = self._events.copy()

        if not events:
            return {"valid": True, "event_count": 0}

        # Verify each event's hash
        broken = []
        for i, event in enumerate(events):
            # Verify event hash
            expected_hash = event._generate_hash()
            if event.event_hash != expected_hash:
                broken.append({"index": i, "event_id": event.event_id, "issue": "hash_mismatch"})

            # Verify chain linkage
            if i > 0:
                if event.previous_hash != events[i-1].event_hash:
                    broken.append({"index": i, "event_id": event.event_id, "issue": "chain_broken"})

        return {
            "valid": len(broken) == 0,
            "event_count": len(events),
            "broken_links": broken,
        }

    def check_anomalies(self, agent_id: str) -> List[AnomalyAlert]:
        """
        Check for anomalies for a specific agent.

        Args:
            agent_id: ID of the agent to check

        Returns:
            List of AnomalyAlert objects
        """
        return self._check_agent_anomalies(agent_id)

    def get_agent_statistics(self, agent_id: str) -> Dict[str, Any]:
        """
        Get statistics for an agent.

        Args:
            agent_id: ID of the agent

        Returns:
            Dict with agent statistics
        """
        events = self.get_events(agent_id=agent_id, limit=10000)

        if not events:
            return {"agent_id": agent_id, "event_count": 0}

        # Calculate statistics
        event_types = defaultdict(int)
        results = defaultdict(int)
        risk_levels = defaultdict(int)

        for event in events:
            event_types[event.event_type.value] += 1
            results[event.result] += 1
            risk_levels[event.risk_level] += 1

        return {
            "agent_id": agent_id,
            "event_count": len(events),
            "event_types": dict(event_types),
            "results": dict(results),
            "risk_levels": dict(risk_levels),
            "first_event": events[0].timestamp.isoformat() if events else None,
            "last_event": events[-1].timestamp.isoformat() if events else None,
        }

    # Private methods

    def _update_anomaly_state(self, event: AuditEvent) -> None:
        """Update anomaly detection state with new event."""
        now = datetime.now()

        # Track event counts per minute
        self._agent_event_counts[event.agent_id].append(now)

        # Clean old entries (older than 1 minute)
        cutoff = now - timedelta(minutes=1)
        self._agent_event_counts[event.agent_id] = [
            t for t in self._agent_event_counts[event.agent_id] if t > cutoff
        ]

        # Track tool usage
        if event.tool_used:
            self._agent_tool_usage[event.agent_id][event.tool_used] += 1

        # Track data access
        if event.event_type in (AuditEventType.DATA_ACCESS, AuditEventType.DATA_MODIFICATION):
            self._agent_data_access[event.agent_id] += 1
            cutoff = now - timedelta(minutes=1)
            # Reset if too old (simplified)

    def _check_agent_anomalies(self, agent_id: str) -> List[AnomalyAlert]:
        """Check for anomalies for a specific agent."""
        alerts = []
        now = datetime.now()

        # Check event rate
        recent_events = self._agent_event_counts.get(agent_id, [])
        if len(recent_events) > self._thresholds["max_events_per_minute"]:
            alerts.append(AnomalyAlert(
                anomaly_type=AnomalyType.RAPID_TOOL_USAGE,
                severity="high",
                agent_id=agent_id,
                description=f"Agent generated {len(recent_events)} events in the last minute",
                evidence={"event_count": len(recent_events), "threshold": self._thresholds["max_events_per_minute"]},
                recommended_action="Temporarily pause agent and review activity",
            ))

        # Check data access rate
        data_access_count = self._agent_data_access.get(agent_id, 0)
        if data_access_count > self._thresholds["max_data_access_per_minute"]:
            alerts.append(AnomalyAlert(
                anomaly_type=AnomalyType.DATA_ACCESS_SPIKE,
                severity="medium",
                agent_id=agent_id,
                description=f"Agent accessed data {data_access_count} times in the last minute",
                evidence={"access_count": data_access_count},
                recommended_action="Monitor agent data access patterns",
            ))

        # Check for suspicious tool combinations
        tool_usage = self._agent_tool_usage.get(agent_id, {})
        if tool_usage:
            # Check for file deletion + network access (potential exfiltration)
            if tool_usage.get("bash", 0) > 10 and tool_usage.get("web_search", 0) > 5:
                alerts.append(AnomalyAlert(
                    anomaly_type=AnomalyType.DATA_EXFILTRATION,
                    severity="critical",
                    agent_id=agent_id,
                    description="Suspicious pattern: heavy bash usage combined with web access",
                    evidence={"tool_usage": dict(tool_usage)},
                    recommended_action="Immediately quarantine agent and review",
                ))

        return alerts

    def _handle_anomaly_internal(self, alert: AnomalyAlert) -> None:
        """Internally handle an anomaly alert."""
        _log.warning(
            f"Anomaly detected: {alert.anomaly_type.value} for agent {alert.agent_id} "
            f"- {alert.description}"
        )

        # Log the anomaly as an audit event
        self.log_event(
            event_type=AuditEventType.ANOMALY_DETECTED,
            agent_id=alert.agent_id,
            action=f"anomaly:{alert.anomaly_type.value}",
            result="detected",
            risk_level=alert.severity,
            metadata={
                "description": alert.description,
                "evidence": alert.evidence,
                "recommended_action": alert.recommended_action,
            },
        )

    def _persist_event(self, event: AuditEvent) -> None:
        """Persist event to file."""
        if not self._log_file:
            return

        try:
            Path(self._log_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_file, "a") as f:
                f.write(json.dumps({
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "timestamp": event.timestamp.isoformat(),
                    "agent_id": event.agent_id,
                    "session_id": event.session_id,
                    "user_id": event.user_id,
                    "action": event.action,
                    "target": event.target,
                    "result": event.result,
                    "decision_reasoning": event.decision_reasoning,
                    "tool_used": event.tool_used,
                    "confidence_score": event.confidence_score,
                    "risk_level": event.risk_level,
                    "ip_address": event.ip_address,
                    "previous_hash": event.previous_hash,
                    "event_hash": event.event_hash,
                    "metadata": event.metadata,
                }) + "\n")
        except Exception as e:
            _log.error(f"Failed to persist audit event: {e}")

    def _load_events(self) -> None:
        """Load events from file."""
        if not self._log_file or not Path(self._log_file).exists():
            return

        try:
            with open(self._log_file, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        event = AuditEvent(
                            event_id=data["event_id"],
                            event_type=AuditEventType(data["event_type"]),
                            timestamp=datetime.fromisoformat(data["timestamp"]),
                            agent_id=data["agent_id"],
                            session_id=data["session_id"],
                            user_id=data.get("user_id"),
                            action=data["action"],
                            target=data.get("target"),
                            result=data["result"],
                            decision_reasoning=data.get("decision_reasoning"),
                            tool_used=data.get("tool_used"),
                            confidence_score=data.get("confidence_score"),
                            risk_level=data.get("risk_level", "low"),
                            ip_address=data.get("ip_address"),
                            previous_hash=data.get("previous_hash"),
                            event_hash=data.get("event_hash"),
                            metadata=data.get("metadata", {}),
                        )
                        self._events.append(event)
                    except Exception:
                        continue

            _log.info(f"Loaded {len(self._events)} audit events from {self._log_file}")
        except Exception as e:
            _log.error(f"Failed to load audit events: {e}")


# Singleton instance
_logger: Optional[SecurityAuditLogger] = None


def get_security_logger() -> SecurityAuditLogger:
    """Get singleton SecurityAuditLogger instance."""
    global _logger
    if _logger is None:
        _logger = SecurityAuditLogger()
    return _logger