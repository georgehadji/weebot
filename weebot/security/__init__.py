"""Security module for Weebot - based on arXiv:2602.20021 findings.

This module provides security enhancements addressing vulnerabilities discovered
in autonomous LLM agents, including:
- State verification to prevent false confidence
- Agent memory sanitization
- Enhanced audit logging
- Identity verification
"""
from weebot.security.state_verifier import StateVerifier, VerificationResult, VerificationStatus
from weebot.security.agent_sanitizer import AgentMemorySanitizer, SanitizedContext
from weebot.security.audit_logger import SecurityAuditLogger, AuditEvent, AuditEventType
from weebot.security.identity_verifier import IdentityVerifier, IdentityClaim, VerificationLevel

__all__ = [
    # State Verifier
    "StateVerifier",
    "VerificationResult", 
    "VerificationStatus",
    # Agent Sanitizer
    "AgentMemorySanitizer",
    "SanitizedContext",
    # Audit Logger
    "SecurityAuditLogger",
    "AuditEvent",
    "AuditEventType",
    # Identity Verifier
    "IdentityVerifier",
    "IdentityClaim",
    "VerificationLevel",
]