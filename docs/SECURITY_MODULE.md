# Security module (`weebot/infrastructure/security/`)

This page used to describe a `weebot/security/` package with a StateVerifier
"integrated into BashTool" and an IdentityVerifier. Neither was ever called by
production code; both were removed in D4 (wave 6, 2026-10-29), and BashTool never
ran a state verifier. The rules and checks they had that the live gates lacked
were moved first:

- `-ExecutionPolicy Bypass`, `cipher /w:` and `cacls` ask in the approval policy,
  and `eval $VAR` is DANGEROUS in BashGuard (from `CommandValidator` and
  `tools/validation.py`);
- the step audit checks that a fully written file still holds what the step wrote
  (from `state_verifier`).

## What lives here now

| File | What it does |
|---|---|
| `agent_sanitizer.py` | Cross-agent contamination checks and agent quarantine |
| `audit_logger.py` | Security audit log |
| `security_validators.py` | `PathValidator` (file paths the tools may touch) and `InputSanitizer` |
| `sqlite_api_key_store.py` | API keys for the web API |
| `trust_boundary_scanner.py` | Prompt-injection signal on tool output |

## Where the gates are

| Concern | Live code |
|---|---|
| Shell commands | `weebot/core/bash_guard.py`, `weebot/core/approval_policy.py`, the guard chain in `weebot/application/services/tool_guards.py` |
| Outbound traffic | `EgressGuard` (`weebot/core/egress_guard.py`) |
| Who may talk to the agent | `weebot/core/gateway_auth.py`, enforced in `weebot/interfaces/gateways/base.py` |
| Untrusted tool output | `weebot/core/trust_boundary.py` |
| Did the step really do it | `StepEvidenceAuditor` (`weebot/application/services/step_evidence_auditor.py`) |

The rules themselves, and the fail-closed defaults, are in `docs/SECURITY_MODEL.md`.
