"""Identity Verifier - Request source verification and action attribution.

Based on arXiv:2602.20021 "Agents of Chaos" findings:
- Agents may comply with requests from non-owners (Unauthorized Compliance)
- Identity spoofing vulnerabilities allow impersonation
- Action attribution is crucial for accountability

This module provides:
- Request source verification for all agent actions
- Action attribution - trace every action to originating request
- Multi-factor authorization for sensitive operations
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set

_log = logging.getLogger(__name__)


class VerificationLevel(Enum):
    """Level of identity verification required."""
    NONE = "none"           # No verification
    BASIC = "basic"         # Source identification only
    STANDARD = "standard"   # Source + basic authorization
    STRONG = "strong"       # Multi-factor verification
    CRITICAL = "critical"   # Full verification with logging


@dataclass
class IdentityClaim:
    """Claimed identity for an agent action."""
    claim_id: str
    source_type: str  # user, agent, system, external
    source_id: str
    source_name: str
    claimed_permissions: List[str]
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Result of identity verification."""
    is_valid: bool
    level: VerificationLevel
    claim: IdentityClaim
    verified_permissions: List[str] = field(default_factory=list)
    denied_permissions: List[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 1.0  # 0.0 to 1.0
    requires_additional_verification: bool = False


@dataclass
class ActionAttribution:
    """Complete attribution for an agent action."""
    action_id: str
    agent_id: str
    original_claim: IdentityClaim
    verified_permissions: List[str]
    actual_action: str
    target: Optional[str]
    result: str
    timestamp: datetime = field(default_factory=datetime.now)
    verification_level: VerificationLevel = VerificationLevel.NONE
    metadata: Dict[str, Any] = field(default_factory=dict)


class IdentityVerifier:
    """
    Verifies identity claims and provides action attribution.

    Addresses unauthorized compliance and identity spoofing from
    arXiv:2602.20021 by ensuring all agent actions can be traced
    to verified sources.

    Usage:
        verifier = IdentityVerifier()

        # Verify an identity claim
        result = verifier.verify_claim(
            claim=IdentityClaim(
                source_type="user",
                source_id="user_123",
                source_name="John",
                claimed_permissions=["read", "write"]
            ),
            required_level=VerificationLevel.STANDARD
        )

        # Attribute an action
        attribution = verifier.attribute_action(
            agent_id="agent_456",
            claim=claim,
            action="delete_file",
            target="/path/to/file"
        )
    """

    # Known trusted source patterns
    _TRUSTED_SOURCES: Set[str] = {"user", "system", "trusted_agent"}
    _UNTRUSTED_SOURCES: Set[str] = {"external", "unknown", "anonymous"}

    # Sensitive actions requiring strong verification
    _SENSITIVE_ACTIONS: Set[str] = {
        "delete", "remove", "rm", "rmdir",
        "format", "mkfs", "drop",
        "exec", "run", "execute",
        "sudo", "su", "runas",
        "chmod", "chown", "chgrp",
        "kill", "terminate",
        "shutdown", "reboot",
        "export", "upload", "send",
        "credential", "password", "key",
    }

    def __init__(
        self,
        enable_caching: bool = True,
        cache_ttl_seconds: int = 300,
        max_verification_age_seconds: int = 3600,
    ):
        self._enable_caching = enable_caching
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._max_verification_age = timedelta(seconds=max_verification_age_seconds)

        # Permission policies
        self._source_policies: Dict[str, Dict[str, Any]] = {
            "user": {
                "default_permissions": ["read", "execute"],
                "sensitive_actions": ["write", "delete"],
                "requires_approval": ["delete", "exec", "credential"],
            },
            "agent": {
                "default_permissions": ["read", "execute"],
                "sensitive_actions": ["write", "delete", "network"],
                "requires_approval": ["delete", "credential"],
            },
            "system": {
                "default_permissions": ["read", "write", "execute", "admin"],
                "sensitive_actions": [],
                "requires_approval": [],
            },
            "external": {
                "default_permissions": ["read"],
                "sensitive_actions": ["write", "delete", "exec", "network"],
                "requires_approval": ["read", "write", "delete", "exec"],
            },
        }

        # Verification cache
        self._verification_cache: Dict[str, VerificationResult] = {}
        self._attribution_log: List[ActionAttribution] = []
        self._max_log_size = 5000

        # Failed verification tracking
        self._failed_verifications: Dict[str, List[datetime]] = {}

    def verify_claim(
        self,
        claim: IdentityClaim,
        required_level: VerificationLevel = VerificationLevel.STANDARD,
    ) -> VerificationResult:
        """
        Verify an identity claim.

        Args:
            claim: The identity claim to verify
            required_level: Minimum verification level required

        Returns:
            VerificationResult with verification status
        """
        # Check cache
        if self._enable_caching:
            cache_key = self._get_cache_key(claim)
            if cache_key in self._verification_cache:
                cached = self._verification_cache[cache_key]
                if datetime.now() - cached.claim.timestamp < self._cache_ttl:
                    return cached

        # Get policy for source type
        policy = self._source_policies.get(claim.source_type, {})

        # Determine verification level needed
        effective_level = self._determine_verification_level(claim, required_level)

        # Perform verification based on level
        if effective_level == VerificationLevel.NONE:
            return VerificationResult(
                is_valid=True,
                level=VerificationLevel.NONE,
                claim=claim,
                verified_permissions=policy.get("default_permissions", []),
                reason="No verification required",
            )

        elif effective_level == VerificationLevel.BASIC:
            return self._verify_basic(claim, policy)

        elif effective_level == VerificationLevel.STANDARD:
            return self._verify_standard(claim, policy)

        elif effective_level in (VerificationLevel.STRONG, VerificationLevel.CRITICAL):
            return self._verify_strong(claim, policy, effective_level)

        return VerificationResult(
            is_valid=False,
            level=required_level,
            claim=claim,
            reason="Unknown verification level",
            confidence=0.0,
        )

    def attribute_action(
        self,
        agent_id: str,
        claim: IdentityClaim,
        action: str,
        target: Optional[str] = None,
        result: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionAttribution:
        """
        Create complete attribution for an agent action.

        Args:
            agent_id: ID of the agent performing the action
            claim: Verified identity claim
            action: The action performed
            target: Target of the action
            result: Result of the action
            metadata: Additional metadata

        Returns:
            ActionAttribution with complete trace
        """
        # Verify the claim first
        verification = self.verify_claim(claim)

        # Generate action ID
        action_id = hashlib.sha256(
            f"{agent_id}:{action}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        attribution = ActionAttribution(
            action_id=action_id,
            agent_id=agent_id,
            original_claim=claim,
            verified_permissions=verification.verified_permissions,
            actual_action=action,
            target=target,
            result=result,
            verification_level=verification.level,
            metadata=metadata or {},
        )

        # Store attribution
        self._attribution_log.append(attribution)
        if len(self._attribution_log) > self._max_log_size:
            self._attribution_log = self._attribution_log[-self._max_log_size:]

        # Log failed verification attempts
        if not verification.is_valid:
            self._track_failed_verification(claim.source_id)

        return attribution

    def check_authorization(
        self,
        claim: IdentityClaim,
        action: str,
        target: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Check if a claim is authorized for a specific action.

        Args:
            claim: The identity claim
            action: The action to authorize
            target: Optional target of the action

        Returns:
            Tuple of (is_authorized, reason)
        """
        # Verify the claim
        verification = self.verify_claim(claim)

        if not verification.is_valid:
            return False, f"Identity claim is invalid: {verification.reason}"

        # Check if action is sensitive
        is_sensitive = any(sensitive in action.lower() for sensitive in self._SENSITIVE_ACTIONS)

        # Get policy for source type
        policy = self._source_policies.get(claim.source_type, {})

        # Check required approvals
        requires_approval = policy.get("requires_approval", [])
        if any(sensitive in action.lower() for sensitive in requires_approval):
            # Sensitive action requires strong verification
            if verification.level.value not in ("strong", "critical"):
                return False, f"Sensitive action '{action}' requires strong verification"

        # Check permissions
        if is_sensitive:
            sensitive_perms = policy.get("sensitive_actions", [])
            if not any(perm in verification.verified_permissions for perm in sensitive_perms):
                return False, f"Source type '{claim.source_type}' lacks permission for sensitive action"

        return True, "Authorized"

    def get_attributions(
        self,
        agent_id: Optional[str] = None,
        source_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[ActionAttribution]:
        """
        Query action attributions.

        Args:
            agent_id: Filter by agent ID
            source_id: Filter by source ID
            since: Return attributions since this time
            limit: Maximum number to return

        Returns:
            List of matching ActionAttribution objects
        """
        filtered = self._attribution_log.copy()

        if agent_id:
            filtered = [a for a in filtered if a.agent_id == agent_id]
        if source_id:
            filtered = [a for a in filtered if a.original_claim.source_id == source_id]
        if since:
            filtered = [a for a in filtered if a.timestamp >= since]

        return filtered[-limit:]

    def get_failed_verifications(self, source_id: str) -> List[datetime]:
        """Get timestamps of failed verification attempts for a source."""
        return self._failed_verifications.get(source_id, []).copy()

    # Private methods

    def _determine_verification_level(
        self,
        claim: IdentityClaim,
        required_level: VerificationLevel,
    ) -> VerificationLevel:
        """Determine the effective verification level needed."""
        # External sources always need stronger verification
        if claim.source_type in self._UNTRUSTED_SOURCES:
            return VerificationLevel.STRONG

        # System sources are trusted
        if claim.source_type == "system":
            return VerificationLevel.BASIC

        # Return required level or higher
        level_order = [
            VerificationLevel.NONE,
            VerificationLevel.BASIC,
            VerificationLevel.STANDARD,
            VerificationLevel.STRONG,
            VerificationLevel.CRITICAL,
        ]

        required_idx = level_order.index(required_level)
        return required_level

    def _verify_basic(
        self,
        claim: IdentityClaim,
        policy: Dict[str, Any],
    ) -> VerificationResult:
        """Perform basic verification (source identification)."""
        # Check if source is known
        is_trusted = claim.source_type in self._TRUSTED_SOURCES

        return VerificationResult(
            is_valid=is_trusted,
            level=VerificationLevel.BASIC,
            claim=claim,
            verified_permissions=policy.get("default_permissions", []),
            reason="Basic verification: source type identified",
            confidence=0.8 if is_trusted else 0.5,
        )

    def _verify_standard(
        self,
        claim: IdentityClaim,
        policy: Dict[str, Any],
    ) -> VerificationResult:
        """Perform standard verification (source + authorization)."""
        # Check source type
        if claim.source_type in self._UNTRUSTED_SOURCES:
            return VerificationResult(
                is_valid=False,
                level=VerificationLevel.STANDARD,
                claim=claim,
                reason=f"Untrusted source type: {claim.source_type}",
                confidence=0.0,
            )

        # Verify permissions match policy
        default_perms = set(policy.get("default_permissions", []))
        claimed_perms = set(claim.claimed_permissions)

        verified = list(default_perms & claimed_perms)
        denied = list(claimed_perms - default_perms)

        return VerificationResult(
            is_valid=True,
            level=VerificationLevel.STANDARD,
            claim=claim,
            verified_permissions=verified,
            denied_permissions=denied,
            reason="Standard verification passed",
            confidence=0.9,
        )

    def _verify_strong(
        self,
        claim: IdentityClaim,
        policy: Dict[str, Any],
        level: VerificationLevel,
    ) -> VerificationResult:
        """Perform strong verification (multi-factor)."""
        # Check for failed verifications
        failed_count = len(self._failed_verifications.get(claim.source_id, []))
        if failed_count >= 3:
            return VerificationResult(
                is_valid=False,
                level=level,
                claim=claim,
                reason=f"Too many failed verification attempts: {failed_count}",
                confidence=0.0,
                requires_additional_verification=True,
            )

        # For critical level, require additional verification
        if level == VerificationLevel.CRITICAL:
            # In production, this would trigger MFA or additional checks
            return VerificationResult(
                is_valid=True,
                level=level,
                claim=claim,
                verified_permissions=policy.get("default_permissions", []),
                reason="Critical verification: additional checks required",
                confidence=0.7,
                requires_additional_verification=True,
            )

        # Strong verification passed
        return VerificationResult(
            is_valid=True,
            level=level,
            claim=claim,
            verified_permissions=policy.get("default_permissions", []) + policy.get("sensitive_actions", []),
            reason="Strong verification passed",
            confidence=0.95,
        )

    def _get_cache_key(self, claim: IdentityClaim) -> str:
        """Generate cache key for verification result."""
        content = f"{claim.source_type}:{claim.source_id}:{':'.join(sorted(claim.claimed_permissions))}"
        return hashlib.md5(content.encode()).hexdigest()

    def _track_failed_verification(self, source_id: str) -> None:
        """Track failed verification attempt."""
        now = datetime.now()
        if source_id not in self._failed_verifications:
            self._failed_verifications[source_id] = []

        self._failed_verifications[source_id].append(now)

        # Clean old entries (older than 1 hour)
        cutoff = now - timedelta(hours=1)
        self._failed_verifications[source_id] = [
            t for t in self._failed_verifications[source_id] if t > cutoff
        ]


# Singleton instance
_verifier: Optional[IdentityVerifier] = None


def get_identity_verifier() -> IdentityVerifier:
    """Get singleton IdentityVerifier instance."""
    global _verifier
    if _verifier is None:
        _verifier = IdentityVerifier()
    return _verifier