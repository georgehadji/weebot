# Security Module Documentation

## Overview

The security module provides comprehensive security enhancements for Weebot based on findings from arXiv:2602.20021 "Agents of Chaos" - a red-teaming study of autonomous LLM agents.

## Installation

No additional dependencies required. The module uses only standard library and existing Weebot dependencies.

## Module Structure

```
weebot/security/
├── __init__.py           # Module exports
├── state_verifier.py     # False confidence detection
├── agent_sanitizer.py    # Cross-agent contamination prevention
├── audit_logger.py       # Comprehensive audit logging
└── identity_verifier.py  # Identity verification & attribution
```

## Components

### 1. StateVerifier

Prevents the critical "false confidence" problem where agents report task completion while the actual system state contradicts those reports.

```python
from weebot.security import StateVerifier, FileOperationClaim, CommandExecutionClaim

verifier = StateVerifier()

# Verify file operations
claim = FileOperationClaim(
    operation="create",
    claimed_path="/path/to/file.py",
    claimed_content="print('hello')"
)
result = await verifier.verify_file_operation(claim)

# Verify command execution
cmd_claim = CommandExecutionClaim(
    command="rm -rf /tmp",
    claimed_returncode=0,
    claimed_output="success"
)
result = await verifier.verify_command_execution(cmd_claim)

# Check statistics
stats = verifier.get_statistics()
```

**Features:**
- File operation verification (create, modify, delete)
- Command execution verification
- Network operation verification
- Caching for performance
- Statistics tracking

### 2. AgentMemorySanitizer

Prevents cross-agent contamination by sanitizing agent memory before handoff.

```python
from weebot.security import AgentMemorySanitizer, SanitizationLevel

sanitizer = AgentMemorySanitizer()

# Sanitize context before handoff
sanitized = sanitizer.sanitize_for_handoff(
    context=agent_context,
    target_agent="research_agent",
    level=SanitizationLevel.STRICT
)

# Detect contamination in content
contamination = sanitizer.detect_contamination(user_input)
if contamination:
    sanitizer.quarantine_agent(agent_id)
```

**Features:**
- Credential removal (API keys, passwords, tokens)
- Dangerous behavior pattern detection
- Prompt injection detection
- Agent quarantine system
- Multiple sanitization levels (MINIMAL, STANDARD, STRICT, PARANOID)

### 3. SecurityAuditLogger

Comprehensive audit logging with cryptographic chain integrity.

```python
from weebot.security import SecurityAuditLogger, AuditEventType

logger = SecurityAuditLogger(log_file="/path/to/audit.log")

# Log events
logger.log_event(
    event_type=AuditEventType.TOOL_EXECUTE,
    agent_id="agent_123",
    action="execute_bash",
    result="success",
    risk_level="high"
)

# Query events
events = logger.get_events(agent_id="agent_123")

# Verify chain integrity
integrity = logger.verify_chain_integrity()

# Get agent statistics
stats = logger.get_agent_statistics("agent_123")
```

**Features:**
- Complete action trails
- Cryptographic chain for tamper detection
- Real-time anomaly detection
- File persistence
- Query and filtering

### 4. IdentityVerifier

Request source verification and action attribution.

```python
from weebot.security import IdentityVerifier, IdentityClaim, VerificationLevel

verifier = IdentityVerifier()

# Verify identity claim
claim = IdentityClaim(
    source_type="user",
    source_id="user_123",
    source_name="John",
    claimed_permissions=["read", "write"]
)
result = verifier.verify_claim(claim, VerificationLevel.STANDARD)

# Check authorization
is_authorized, reason = verifier.check_authorization(
    claim=claim,
    action="delete_file",
    target="/path"
)

# Attribute action
attribution = verifier.attribute_action(
    agent_id="agent_456",
    claim=claim,
    action="create_file",
    target="/new/file.txt"
)
```

**Features:**
- Multi-level verification (NONE, BASIC, STANDARD, STRONG, CRITICAL)
- Permission policies per source type
- Action attribution
- Authorization checks for sensitive operations

## Usage Examples

### BashTool Integration (v2.4.0+)

The StateVerifier is integrated into `BashTool` for automatic post-execution verification of critical commands.

```python
from weebot.tools.bash_tool import BashTool

# BashTool automatically verifies critical commands
# (create, delete, download, install, etc.)
bash_tool = BashTool()

# Execute a critical command - verification happens automatically
result = await bash_tool.execute("pip install requests")

# If verification confidence is low, a warning is added:
# "[WARNING: Execution verification confidence 0.75]"
print(result.output)
```

**How it works:**
1. Command passes security analysis (layers 1-4)
2. Command is executed in sandbox
3. For critical commands (delete, create, download, install), StateVerifier verifies the result
4. If verification fails or confidence is low, a warning is appended to output

**Verified command patterns:**
- `delete`, `remove`, `rm` - File deletion
- `mkdir`, `create`, `new-file` - File creation
- `download`, `curl`, `wget` - Network downloads
- `install`, `pip install`, `npm install` - Package installation

### Complete Security Flow

```python
from weebot.security import (
    get_state_verifier,
    get_agent_sanitizer,
    get_security_logger,
    get_identity_verifier,
    VerificationLevel,
    SanitizationLevel,
    AuditEventType,
)

# Initialize components
verifier = get_state_verifier()
sanitizer = get_agent_sanitizer()
logger = get_security_logger()
identity_verifier = get_identity_verifier()

# 1. Verify identity
claim = IdentityClaim(
    source_type="user",
    source_id="user_1",
    source_name="Alice",
    claimed_permissions=["read", "write", "execute"]
)
identity_result = identity_verifier.verify_claim(claim, VerificationLevel.STANDARD)

# 2. Log the action
logger.log_event(
    event_type=AuditEventType.DECISION_POINT,
    agent_id="agent_1",
    action="verify_identity",
    result="success" if identity_result.is_valid else "failure",
    risk_level="low"
)

# 3. Sanitize context
context = {
    "agent_id": "agent_1",
    "memory": [
        {"content": "API key: sk-1234567890abcdefghijklmnopqrstuvwxyz"},
        {"content": "User request: create file"}
    ]
}
sanitized = sanitizer.sanitize_for_handoff(
    context=context,
    target_agent="agent_2",
    level=SanitizationLevel.STANDARD
)

# 4. Verify execution result
file_claim = FileOperationClaim(
    operation="create",
    claimed_path="/output/result.txt",
    claimed_content="execution result"
)
verification = await verifier.verify_file_operation(file_claim)

# 5. Log final result
logger.log_event(
    event_type=AuditEventType.TOOL_SUCCESS,
    agent_id="agent_1",
    action="create_file",
    result="success" if verification.is_trusted else "failed_verification",
    risk_level="medium"
)
```

## Testing

Run security module tests:

```bash
pytest weebot/tests/unit/test_security.py -v
```

All 21 tests should pass.

## Vulnerability Coverage

Based on arXiv:2602.20021 findings:

| Vulnerability | Mitigation |
|--------------|------------|
| False Confidence | StateVerifier |
| Cross-Agent Contamination | AgentMemorySanitizer |
| Unauthorized Compliance | IdentityVerifier |
| Information Disclosure | AgentMemorySanitizer + AuditLogger |
| Resource Exhaustion | Already addressed (CircuitBreaker) |

## Configuration

Default settings work out of the box. For customization:

```python
# StateVerifier
verifier = StateVerifier(
    enable_file_verification=True,
    enable_command_verification=True,
    enable_network_verification=True,
    max_verification_time=5.0
)

# AgentMemorySanitizer
sanitizer = AgentMemorySanitizer(
    default_level=SanitizationLevel.STANDARD,
    enable_quarantine=True
)

# SecurityAuditLogger
logger = SecurityAuditLogger(
    log_file="/path/to/audit.log",
    enable_anomaly_detection=True,
    enable_file_persistence=True,
    max_events_in_memory=10000
)

# IdentityVerifier
verifier = IdentityVerifier(
    enable_caching=True,
    cache_ttl_seconds=300,
    max_verification_age_seconds=3600
)
```