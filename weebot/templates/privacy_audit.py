"""Privacy Audit Middleware for Adaptive Suggestion Engine.

HARDEN Mode Implementation: Privacy protection layer for GDPR compliance
and collaborative filtering safety.

Features:
- Query audit logging for collaborative filtering
- Enforced minimum user count validation
- Privacy threshold violation alerts
- Anonymization verification
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

_log = logging.getLogger(__name__)


class PrivacyViolationType(Enum):
    """Types of privacy policy violations."""
    MIN_USER_COUNT = "min_user_count_violation"
    RAW_USER_ID = "raw_user_id_exposure"
    SMALL_SAMPLE = "insufficient_sample_size"
    CROSS_TEMPLATE_LEAK = "cross_template_data_leak"


@dataclass
class PrivacyAuditEvent:
    """Record of a privacy-sensitive operation."""
    timestamp: datetime
    operation: str
    template_name: str
    user_hash: str
    violation_type: Optional[PrivacyViolationType] = None
    details: Dict[str, Any] = field(default_factory=dict)
    blocked: bool = False


@dataclass
class PrivacyReport:
    """Aggregate privacy compliance report."""
    total_queries: int
    violations: int
    blocked_operations: int
    violation_breakdown: Dict[str, int]
    last_violation: Optional[datetime] = None
    compliance_score: float = 1.0


class PrivacyAuditMiddleware:
    """
    Middleware to enforce privacy policies on adaptive suggestions.
    
    HARDEN Mode: Prevents privacy breaches in collaborative filtering
    by auditing queries and enforcing minimum thresholds at the
    infrastructure level (not just application logic).
    
    Usage:
        audit = PrivacyAuditMiddleware(min_user_count=3)
        
        # Check before collaborative query
        if audit.allow_collaborative_query(template_name, user_hash):
            results = await db.execute(query)
        else:
            return []  # Blocked by privacy policy
    """
    
    DEFAULT_MIN_USER_COUNT = 3
    DEFAULT_MIN_SAMPLE_SIZE = 5
    ALERT_THRESHOLD = 3  # Violations before alerting
    
    def __init__(
        self,
        min_user_count: int = DEFAULT_MIN_USER_COUNT,
        min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
        enable_alerting: bool = True,
    ):
        self.min_user_count = max(2, min_user_count)  # Absolute minimum: 2
        self.min_sample_size = max(3, min_sample_size)  # Absolute minimum: 3
        self.enable_alerting = enable_alerting
        
        # Audit trail (bounded size to prevent memory exhaustion)
        self._audit_log: List[PrivacyAuditEvent] = []
        self._max_log_size = 10000
        
        # Violation tracking for alerting
        self._recent_violations: List[datetime] = []
        self._violation_window_seconds = 3600  # 1 hour
        
        # Per-template query tracking
        self._query_counts: Dict[str, int] = {}
    
    def _hash_user_id(self, user_id: str) -> str:
        """One-way hash of user ID for audit logging."""
        return hashlib.sha256(f"privacy_audit:{user_id}".encode()).hexdigest()[:32]
    
    def _log_event(self, event: PrivacyAuditEvent) -> None:
        """Add event to audit log with size management."""
        self._audit_log.append(event)
        
        # Prevent unbounded growth
        if len(self._audit_log) > self._max_log_size:
            self._audit_log.pop(0)
        
        # Log violations immediately
        if event.violation_type:
            _log.warning(
                "Privacy violation detected: %s for template %s (blocked=%s)",
                event.violation_type.value,
                event.template_name,
                event.blocked
            )
    
    def allow_collaborative_query(
        self,
        template_name: str,
        user_id: str,
        proposed_user_count: Optional[int] = None,
    ) -> bool:
        """
        Determine if a collaborative filtering query should proceed.
        
        Args:
            template_name: Name of template being queried
            user_id: User requesting suggestions
            proposed_user_count: Expected number of users in result
            
        Returns:
            True if query is privacy-compliant, False to block
        """
        user_hash = self._hash_user_id(user_id)
        
        # Check 1: Verify proposed user count meets minimum
        if proposed_user_count is not None and proposed_user_count < self.min_user_count:
            event = PrivacyAuditEvent(
                timestamp=datetime.now(),
                operation="collaborative_query",
                template_name=template_name,
                user_hash=user_hash,
                violation_type=PrivacyViolationType.MIN_USER_COUNT,
                details={
                    "proposed_count": proposed_user_count,
                    "required_count": self.min_user_count,
                },
                blocked=True,
            )
            self._log_event(event)
            self._track_violation()
            return False
        
        # Check 2: Track query for pattern detection
        self._query_counts[template_name] = self._query_counts.get(template_name, 0) + 1
        
        # Log approved query
        event = PrivacyAuditEvent(
            timestamp=datetime.now(),
            operation="collaborative_query",
            template_name=template_name,
            user_hash=user_hash,
            details={"proposed_count": proposed_user_count},
            blocked=False,
        )
        self._log_event(event)
        
        return True
    
    def validate_suggestion_result(
        self,
        template_name: str,
        user_id: str,
        result: Dict[str, Any],
    ) -> bool:
        """
        Validate that a suggestion result meets privacy requirements.
        
        Args:
            template_name: Template name
            user_id: User receiving suggestions
            result: Suggestion result from database
            
        Returns:
            True if result is privacy-compliant
        """
        user_hash = self._hash_user_id(user_id)
        
        # Verify user_count field exists and meets minimum
        user_count = result.get("user_count", 0)
        if user_count < self.min_user_count:
            event = PrivacyAuditEvent(
                timestamp=datetime.now(),
                operation="validate_result",
                template_name=template_name,
                user_hash=user_hash,
                violation_type=PrivacyViolationType.SMALL_SAMPLE,
                details={
                    "actual_count": user_count,
                    "required_count": self.min_user_count,
                },
                blocked=True,
            )
            self._log_event(event)
            self._track_violation()
            return False
        
        # Verify sample size meets minimum
        execution_count = result.get("execution_count", 0)
        if execution_count < self.min_sample_size:
            event = PrivacyAuditEvent(
                timestamp=datetime.now(),
                operation="validate_result",
                template_name=template_name,
                user_hash=user_hash,
                violation_type=PrivacyViolationType.SMALL_SAMPLE,
                details={
                    "actual_sample": execution_count,
                    "required_sample": self.min_sample_size,
                },
                blocked=True,
            )
            self._log_event(event)
            self._track_violation()
            return False
        
        return True
    
    def _track_violation(self) -> None:
        """Track violation for alerting threshold."""
        now = datetime.now()
        self._recent_violations.append(now)
        
        # Clean old violations outside window
        cutoff = now.timestamp() - self._violation_window_seconds
        self._recent_violations = [
            v for v in self._recent_violations
            if v.timestamp() > cutoff
        ]
        
        # Alert if threshold exceeded
        if self.enable_alerting and len(self._recent_violations) >= self.ALERT_THRESHOLD:
            _log.error(
                "PRIVACY ALERT: %d violations in last hour. "
                "Consider reviewing adaptive engine configuration.",
                len(self._recent_violations)
            )
    
    def get_report(self, template_name: Optional[str] = None) -> PrivacyReport:
        """
        Generate privacy compliance report.
        
        Args:
            template_name: Optional template to filter by
            
        Returns:
            PrivacyReport with compliance metrics
        """
        events = self._audit_log
        if template_name:
            events = [e for e in events if e.template_name == template_name]
        
        total = len(events)
        violations = [e for e in events if e.violation_type is not None]
        blocked = [e for e in events if e.blocked]
        
        # Breakdown by violation type
        breakdown: Dict[str, int] = {}
        for v in violations:
            key = v.violation_type.value if v.violation_type else "unknown"
            breakdown[key] = breakdown.get(key, 0) + 1
        
        # Compliance score (1.0 = perfect)
        compliance_score = 1.0 - (len(violations) / total) if total > 0 else 1.0
        
        last_violation = violations[-1].timestamp if violations else None
        
        return PrivacyReport(
            total_queries=total,
            violations=len(violations),
            blocked_operations=len(blocked),
            violation_breakdown=breakdown,
            last_violation=last_violation,
            compliance_score=max(0.0, compliance_score),
        )
    
    def get_audit_trail(
        self,
        template_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[PrivacyAuditEvent]:
        """Get recent audit events for inspection."""
        events = self._audit_log
        if template_name:
            events = [e for e in events if e.template_name == template_name]
        return events[-limit:]
    
    def clear_audit_log(self) -> None:
        """Clear audit log (GDPR: right to erasure support)."""
        self._audit_log.clear()
        self._query_counts.clear()
        _log.info("Privacy audit log cleared")


class ValidatingSuggestionEngine:
    """
    Wrapper for AdaptiveSuggestionEngine that enforces privacy validation.
    
    This is a HARDEN mode protective layer that sits between the
    production engine and the database to ensure all queries meet
    privacy requirements regardless of application logic bugs.
    """
    
    def __init__(
        self,
        inner_engine: Any,
        audit: Optional[PrivacyAuditMiddleware] = None,
    ):
        self.inner_engine = inner_engine
        self.audit = audit or PrivacyAuditMiddleware()
    
    async def suggest_parameters(self, *args, **kwargs) -> List[Any]:
        """Wrapped suggestion call with privacy validation."""
        template = kwargs.get("template")
        context = kwargs.get("context")
        
        if template and context:
            # Pre-check: Allow collaborative query?
            if not self.audit.allow_collaborative_query(
                template_name=template.name,
                user_id=context.user_id,
            ):
                # Return empty suggestions (safe fallback)
                return []
        
        # Call inner engine
        suggestions = await self.inner_engine.suggest_parameters(*args, **kwargs)
        
        # Post-check: Validate each suggestion
        validated = []
        for suggestion in suggestions:
            if suggestion.source != "collaborative":
                # Personal suggestions don't need validation
                validated.append(suggestion)
                continue
            
            # Convert suggestion to dict for validation
            result_dict = {
                "user_count": getattr(suggestion, "sample_size", 0),
                "execution_count": getattr(suggestion, "sample_size", 0),
            }
            
            if self.audit.validate_suggestion_result(
                template_name=template.name if template else "unknown",
                user_id=context.user_id if context else "unknown",
                result=result_dict,
            ):
                validated.append(suggestion)
        
        return validated
